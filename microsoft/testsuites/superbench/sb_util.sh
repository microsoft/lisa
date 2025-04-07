#!/usr/bin/env bash

set -ex

# Possible commands are "install" and "run"
export sub_command=""

export sb_repo_dir=""
export sb_image_tag=""
export sb_config_file=""

# This is the URL to extract SKU of the machine it is run on
AZURE_SKU_URL='http://169.254.169.254/metadata/instance/compute/vmSize?api-version=2020-06-01&format=text'

function parse_args() {
    ## Process command line parameters
    while [[ "$#" -gt 0 ]]; do
	case $1 in
	    --action) sub_command=$2; shift ;;
            --sb-repo-dir) sb_repo_dir="$2"; shift ;;
            --sb-image-tag) sb_image_tag="$2"; shift ;;
            --sb-config-file) sb_config_file="$2"; shift ;;
            *) echo "Unknown parameter: $1"; exit 1 ;;
	esac
	shift
    done
}

# Make sure none of the variables are empty
function assert_non_empty {
    for varName in "$@" ; do
	if [ -z "${!varName}" ] ; then
	    echo "\"${varName}\" is empty, aborting execution."
	    echo "Usage:\nsetup_sb.sh --action (install|run|verify)"
	    echo "\t--sb-repo-dir <sb repo path>\n--sb-image-tag <sb container tag>\n--sb-config-file <superbench test config>"
	    exit 22 # EINVAL in case someone is processing the exit status
	fi
    done
}

function superbench_setup() {
    assert_non_empty sb_repo_dir sb_image_tag
    # Explicitly set working dir to show we are in home dir intentionally.
    cd "$HOME"

    # Install python 3.11 from scratch
    wget https://www.python.org/ftp/python/3.11.11/Python-3.11.11.tar.xz -O- | tar Jxf -
    cd Python-3.11.11
    ./configure --enable-optimizations
    sudo make -j16
    sudo make altinstall

    # create and activate virtual environment for sb pip
    python3.11 -m venv ~/sb_venv
    source "$HOME/sb_venv/bin/activate"
    export PATH=$PATH:$HOME/.local/bin

    pip install pip_system_certs
    pip install --upgrade pip wheel setuptools==65.7
    pip install ansible-core==2.17

    ## Superbench installation and setup
    cd "$HOME"
    git clone -b v0.11.0 https://github.com/microsoft/superbenchmark "${sb_repo_dir}"
    cd "${sb_repo_dir}"

    # Install superbench modules
    pip install .
    pip uninstall -y ansible-core && pip install ansible-core==2.17
    make postinstall

    # This is for superbench to run locally
    echo -e "[all]\nlocalhost ansible_connection=local" > local.ini

    sb deploy -f local.ini -i "${sb_image_tag}" --output-dir deploy_output

    echo "SUPERBENCH: deployment successful."
}

function run_sb_test() {
    assert_non_empty sb_config_file sb_repo_dir

    source "$HOME/sb_venv/bin/activate"
    cd "${sb_repo_dir}"

    # Make output dirs for system information and superbench test
    mkdir -p outputs/{node_info,sb_run}

    # Collect system information for populating dashboard schema
    sudo sb node info --output-dir outputs/node_info

    # Extract SKU, assume this is an azure VM and ignore failures.
    if ! curl --header 'Metadata: true' "${AZURE_SKU_URL}" -o outputs/node_info/sku.txt ; then
        echo "unknown" > outputs/node_info/sku.txt
    fi

    # superbench test invocation

    # We do not want to fail here, output json provides the result
    set +e
    sb run -f local.ini -c "$HOME/${sb_config_file}" --output-dir outputs/sb_run
    sb_retval=$?
    set -e
    # print return value for housekeeping
    echo "sb run returned: $sb_retval"

    # We are still in superbench repo directory. This tgz file will be copied
    # back to the test agent for processing.
    tar -zcf outputs.tgz outputs
}

# Verify whether superbench is installed and binary can be launched
function verify() {
    assert_non_empty sb_repo_dir

    if [ ! -f ~/sb_venv/bin/activate ] ; then
	echo "Python virtual environment not setup at '~/sb_venv/bin/activate'"
	return 1
    fi
    if [ ! -d "${sb_repo_dir}" ] ; then
	echo "superbench repository not found at ${sb_repo_dir}"
	return 2
    fi
    source "$HOME/sb_venv/bin/activate"
    if ! sb version ; then
	echo "superbench not installed"
	return 3
    fi

    echo "superbench version $(sb version) installed."
    return 0
}

parse_args "$@"
assert_non_empty sub_command

case ${sub_command} in
    install) superbench_setup ;;
    run) run_sb_test ;;
    verify) verify ;;
    *) echo "Unknown action: $1"; exit 1 ;;
esac
