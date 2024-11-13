#include <fcntl.h>
#include <linux/cdrom.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

// A small program to check the status code of the CD-ROM device.
// Expected value is CDS_NO_DISK, assuming the VM has been rebooted 
// after provisioning.
// authors: mamcgove@microsoft.com, rahugupta@microsoft.com

int
main (int argc, char *argv[])
{

  int slot, result, fd;

  fd = open ("/dev/cdrom", O_RDONLY | O_NONBLOCK);
  if (fd < 0)
    {
      printf ("Error: could not open /dev/cdrom\n");
      exit (-1);
    }
  slot = 0;
  result = ioctl (fd, CDROM_DRIVE_STATUS, slot);
  switch (result)
    {
    case CDS_NO_DISC:
      // This is our expected value after reboot,
      // There should be no disk (or iso) in the drive.
      printf ("CDS_NO_DISC\n");
      exit (0);
    
    // otherwise something is off.
    // log the disk drive status code and return 1
    case CDS_NO_INFO:
      printf ("CDS_NO_INFO\n");
      break;
    case CDS_TRAY_OPEN:
      printf ("CDS_TRAY_OPEN\n");
      break;
    case CDS_DRIVE_NOT_READY:
      printf ("CDS_DRIVE_NOT_READY\n");
      break;
    case CDS_DISC_OK:
      printf ("CDS_DISC_OK\n");
      break;
    default:
      printf ("UNKNOWN_STATUS_CODE!\n");
    }

  exit (1);
}
