/* SPDX-License-Identifier: BSD-3-Clause
 *
 * azure_hotplug_mon - watch kernel uevents for NIC hotplug/removal on Azure.
 *
 * Listens on the raw NETLINK_KOBJECT_UEVENT socket (kernel multicast group 1)
 * and reports the events that matter to a DPDK application running with the
 * mlx5, mana or netvsc PMDs:
 *
 *   VF_PCI_ADD/REMOVE   accelerated-networking VF appearing/disappearing
 *   UVERBS_ADD/REMOVE   /dev/infiniband/uverbsN - earliest mlx5 removal signal
 *   IBDEV_ADD/REMOVE    mlx5_N / mana_N RDMA device
 *   NETDEV_ADD/REMOVE   VF or synthetic netdev (what netvsc MAC-matches on)
 *   VMBUS_NETVSC_*      synthetic netvsc device on the vmbus
 *   VMBUS_ADD/REMOVE    any other vmbus device
 *
 * This deliberately does not use EAL: rte_dev_event_monitor_start() only
 * parses SUBSYSTEM=pci/uio/vfio *and* requires PCI_SLOT_NAME, so it silently
 * drops every vmbus, net and infiniband event.
 *
 * Build:
 *   gcc -O2 -Wall -Wextra -o azure-hotplug-mon azure_hotplug_mon.c
 *
 * Run (needs CAP_NET_ADMIN, i.e. root in practice):
 *   sudo ./azure-hotplug-mon          # relevant events only
 *   sudo ./azure-hotplug-mon -a       # every subsystem
 *   sudo ./azure-hotplug-mon -v       # dump all properties per event
 */

#define _GNU_SOURCE	/* struct ucred, SCM_CREDENTIALS */

#include <ctype.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <sys/socket.h>
#include <sys/types.h>
#include <linux/netlink.h>

/* Kernel caps a uevent payload at 2048 bytes; leave generous headroom. */
#define UEV_BUF_SZ	16384
#define RCVBUF_SZ	(2 * 1024 * 1024)

/* netvsc vmbus class GUID, from drivers/net/netvsc/hn_ethdev.c hn_net_ids[]:
 * f8615163-df3e-46c5-913f-f2d2f965ed0e, as it appears in MODALIAS.
 */
#define NETVSC_MODALIAS	"vmbus:f8615163df3e46c5913ff2d2f965ed0e"

struct uevent {
	const char *header;	/* "add@/devices/..." */
	const char *action;
	const char *subsystem;
	const char *devpath;
	const char *driver;
	const char *pci_slot;	/* PCI_SLOT_NAME */
	const char *interface;	/* INTERFACE (net) */
	const char *name;	/* NAME (infiniband, infiniband_verbs) */
	const char *devname;	/* DEVNAME */
	const char *modalias;
	const char *devtype;
};

static volatile sig_atomic_t stop_flag;

static void
sig_handler(int signum)
{
	(void)signum;
	stop_flag = 1;
}

/* Return the value of "key=" in line, or NULL if line is a different key. */
static const char *
prop(const char *line, const char *key)
{
	size_t klen = strlen(key);

	if (strncmp(line, key, klen) == 0 && line[klen] == '=')
		return line + klen + 1;
	return NULL;
}

/* True if s[0..35] is a 8-4-4-4-12 hex GUID, i.e. a vmbus device directory. */
static bool
is_guid(const char *s, size_t len)
{
	size_t i;

	if (len != 36)
		return false;

	for (i = 0; i < 36; i++) {
		if (i == 8 || i == 13 || i == 18 || i == 23) {
			if (s[i] != '-')
				return false;
		} else if (!isxdigit((unsigned char)s[i])) {
			return false;
		}
	}
	return true;
}

/*
 * On Azure an accelerated-networking VF is enumerated behind the pci-hyperv
 * bridge, so its DEVPATH always contains a vmbus GUID path segment, e.g.
 *   /devices/6f9b9d4c-.../pci0001:00/0001:00:02.0/net/eth1
 * A plain (non-vmbus) PCI device never does.
 */
static bool
is_azure_vf(const char *devpath)
{
	const char *seg = devpath;

	if (devpath == NULL)
		return false;

	while (seg != NULL) {
		const char *end = strchr(seg + 1, '/');
		size_t len = (end != NULL) ? (size_t)(end - seg - 1)
					   : strlen(seg + 1);

		if (is_guid(seg + 1, len))
			return true;
		seg = end;
	}
	return false;
}

/*
 * Map the event onto a short tag. Returns NULL when the event is not one of
 * the Azure NIC cases (caller drops it unless -a was given).
 */
static const char *
classify(const struct uevent *ev, bool vf)
{
	bool add;

	if (ev->action == NULL || ev->subsystem == NULL)
		return NULL;

	if (strcmp(ev->action, "add") == 0)
		add = true;
	else if (strcmp(ev->action, "remove") == 0)
		add = false;
	else
		return NULL;	/* change/bind/unbind/move - not hotplug */

	if (strcmp(ev->subsystem, "pci") == 0) {
		if (vf)
			return add ? "VF_PCI_ADD" : "VF_PCI_REMOVE";
		return add ? "PCI_ADD" : "PCI_REMOVE";
	}
	if (strcmp(ev->subsystem, "infiniband_verbs") == 0)
		return add ? "UVERBS_ADD" : "UVERBS_REMOVE";
	if (strcmp(ev->subsystem, "infiniband") == 0)
		return add ? "IBDEV_ADD" : "IBDEV_REMOVE";
	if (strcmp(ev->subsystem, "net") == 0)
		return add ? "NETDEV_ADD" : "NETDEV_REMOVE";
	if (strcmp(ev->subsystem, "vmbus") == 0) {
		if (ev->modalias != NULL &&
		    strcmp(ev->modalias, NETVSC_MODALIAS) == 0)
			return add ? "VMBUS_NETVSC_ADD" : "VMBUS_NETVSC_REMOVE";
		return add ? "VMBUS_ADD" : "VMBUS_REMOVE";
	}
	return NULL;
}

static void
print_event(const struct uevent *ev, const char *tag, bool vf)
{
	struct timespec ts;
	struct tm tm;
	char when[16] = "??:??:??";

	if (clock_gettime(CLOCK_REALTIME, &ts) == 0 &&
	    localtime_r(&ts.tv_sec, &tm) != NULL)
		strftime(when, sizeof(when), "%H:%M:%S", &tm);

	printf("[%s.%03ld] %-18s subsystem=%s", when, ts.tv_nsec / 1000000,
	       tag, ev->subsystem != NULL ? ev->subsystem : "?");

	if (ev->pci_slot != NULL)
		printf(" pci=%s", ev->pci_slot);
	if (ev->driver != NULL)
		printf(" driver=%s", ev->driver);
	if (ev->interface != NULL)
		printf(" ifname=%s", ev->interface);
	if (ev->name != NULL)
		printf(" name=%s", ev->name);
	if (ev->devname != NULL)
		printf(" devnode=/dev/%s", ev->devname);
	if (vf)
		printf(" azure_vf=yes");
	if (ev->devpath != NULL)
		printf(" devpath=%s", ev->devpath);
	printf("\n");
	fflush(stdout);
}

static int
uev_socket_create(void)
{
	struct sockaddr_nl addr;
	int fd, one = 1, bufsz = RCVBUF_SZ;

	fd = socket(PF_NETLINK, SOCK_RAW | SOCK_CLOEXEC,
		    NETLINK_KOBJECT_UEVENT);
	if (fd < 0) {
		fprintf(stderr, "socket(NETLINK_KOBJECT_UEVENT): %s\n",
			strerror(errno));
		return -1;
	}

	/* Big receive buffer: a VM-level hotplug can burst dozens of events. */
	if (setsockopt(fd, SOL_SOCKET, SO_RCVBUFFORCE, &bufsz,
		       sizeof(bufsz)) < 0)
		(void)setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &bufsz,
				 sizeof(bufsz));

	/* Credentials let us drop anything not sent by the kernel. */
	if (setsockopt(fd, SOL_SOCKET, SO_PASSCRED, &one, sizeof(one)) < 0)
		fprintf(stderr, "warning: SO_PASSCRED failed: %s\n",
			strerror(errno));

	memset(&addr, 0, sizeof(addr));
	addr.nl_family = AF_NETLINK;
	addr.nl_pid = 0;	/* let the kernel assign */
	addr.nl_groups = 1;	/* group 1 = kernel uevents, not udev's copy */

	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		fprintf(stderr, "bind: %s%s\n", strerror(errno),
			errno == EPERM ? " (need root/CAP_NET_ADMIN)" : "");
		close(fd);
		return -1;
	}
	return fd;
}

/* Receive one message; returns length, 0 to skip, -1 on fatal error. */
static ssize_t
uev_recv(int fd, char *buf, size_t bufsz)
{
	struct sockaddr_nl snl;
	struct iovec iov;
	union {
		struct cmsghdr hdr;
		char buf[CMSG_SPACE(sizeof(struct ucred))];
	} cmsg;
	struct msghdr msg;
	struct cmsghdr *cm;
	struct ucred *cred;
	ssize_t len;

	iov.iov_base = buf;
	iov.iov_len = bufsz - 1;

	memset(&msg, 0, sizeof(msg));
	msg.msg_name = &snl;
	msg.msg_namelen = sizeof(snl);
	msg.msg_iov = &iov;
	msg.msg_iovlen = 1;
	msg.msg_control = &cmsg;
	msg.msg_controllen = sizeof(cmsg);

	len = recvmsg(fd, &msg, 0);
	if (len < 0) {
		if (errno == EINTR || errno == EAGAIN)
			return 0;
		if (errno == ENOBUFS) {
			fprintf(stderr,
				"warning: uevent buffer overrun, events lost\n");
			return 0;
		}
		fprintf(stderr, "recvmsg: %s\n", strerror(errno));
		return -1;
	}
	if (len == 0)
		return 0;

	/* Only the kernel (port id 0, uid 0) is allowed to talk to us. */
	if (snl.nl_pid != 0)
		return 0;

	cm = CMSG_FIRSTHDR(&msg);
	if (cm == NULL || cm->cmsg_type != SCM_CREDENTIALS)
		return 0;
	cred = (struct ucred *)CMSG_DATA(cm);
	if (cred->uid != 0)
		return 0;

	buf[len] = '\0';
	return len;
}

static void
uev_parse(char *buf, size_t len, struct uevent *ev)
{
	size_t off;

	memset(ev, 0, sizeof(*ev));
	ev->header = buf;

	/* Payload is the header line, then NUL-separated KEY=VALUE pairs. */
	off = strlen(buf) + 1;
	while (off < len) {
		char *line = buf + off;
		size_t llen = strlen(line);
		const char *val;

		if (llen == 0) {
			off++;
			continue;
		}

		if ((val = prop(line, "ACTION")) != NULL)
			ev->action = val;
		else if ((val = prop(line, "SUBSYSTEM")) != NULL)
			ev->subsystem = val;
		else if ((val = prop(line, "DEVPATH")) != NULL)
			ev->devpath = val;
		else if ((val = prop(line, "DRIVER")) != NULL)
			ev->driver = val;
		else if ((val = prop(line, "PCI_SLOT_NAME")) != NULL)
			ev->pci_slot = val;
		else if ((val = prop(line, "INTERFACE")) != NULL)
			ev->interface = val;
		else if ((val = prop(line, "NAME")) != NULL)
			ev->name = val;
		else if ((val = prop(line, "DEVNAME")) != NULL)
			ev->devname = val;
		else if ((val = prop(line, "MODALIAS")) != NULL)
			ev->modalias = val;
		else if ((val = prop(line, "DEVTYPE")) != NULL)
			ev->devtype = val;

		off += llen + 1;
	}
}

static void
dump_raw(const char *buf, size_t len)
{
	size_t off = 0;

	while (off < len) {
		size_t llen = strlen(buf + off);

		if (llen > 0)
			printf("\t| %s\n", buf + off);
		off += llen + 1;
	}
}

static void
usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [-a] [-v]\n"
		"  -a  report every subsystem, not just Azure NIC events\n"
		"  -v  dump all uevent properties for each reported event\n",
		argv0);
}

int
main(int argc, char **argv)
{
	struct sigaction sa;
	struct pollfd pfd;
	char buf[UEV_BUF_SZ];
	bool show_all = false, verbose = false;
	int fd, opt, rc = EXIT_SUCCESS;

	while ((opt = getopt(argc, argv, "avh")) != -1) {
		switch (opt) {
		case 'a':
			show_all = true;
			break;
		case 'v':
			verbose = true;
			break;
		case 'h':
			usage(argv[0]);
			return EXIT_SUCCESS;
		default:
			usage(argv[0]);
			return EXIT_FAILURE;
		}
	}

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = sig_handler;
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGTERM, &sa, NULL);

	fd = uev_socket_create();
	if (fd < 0)
		return EXIT_FAILURE;

	printf("watching kernel uevents (ctrl-c to stop)\n");
	fflush(stdout);

	pfd.fd = fd;
	pfd.events = POLLIN;

	while (!stop_flag) {
		struct uevent ev;
		const char *tag;
		ssize_t len;
		bool vf;

		if (poll(&pfd, 1, -1) < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "poll: %s\n", strerror(errno));
			rc = EXIT_FAILURE;
			break;
		}
		if (!(pfd.revents & POLLIN))
			continue;

		len = uev_recv(fd, buf, sizeof(buf));
		if (len < 0) {
			rc = EXIT_FAILURE;
			break;
		}
		if (len == 0)
			continue;

		uev_parse(buf, (size_t)len, &ev);
		vf = is_azure_vf(ev.devpath);
		tag = classify(&ev, vf);

		if (tag == NULL) {
			if (!show_all)
				continue;
			tag = "OTHER";
		}

		print_event(&ev, tag, vf);
		if (verbose)
			dump_raw(buf, (size_t)len);
	}

	close(fd);
	return rc;
}
