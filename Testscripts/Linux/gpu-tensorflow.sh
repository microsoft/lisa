#!/bin/bash

########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
########################################################################

#######################################################################
#
# Install dependencies and tensorflow-gpu
#
#######################################################################
InstallCUDAToolKit() {
    LogMsg "Install CUDA toolkit packages $CudaToolkitVersion..."
    case $DISTRO in
    redhat_7|centos_7)
        CUDA_REPO_PKG="cuda-repo-rhel7-${CUDADriverVersion}.x86_64.rpm"
        LogMsg "Using ${CUDA_REPO_PKG}"

        wget http://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
        if [ $? -ne 0 ]; then
            LogErr "Failed to download ${CUDA_REPO_PKG}"
            SetTestStateAborted
            exit 1
        fi

        rpm -ivh /tmp/"${CUDA_REPO_PKG}"
        yum --nogpgcheck -y install $CudaToolkitVersion
        if [ $? -ne 0 ]; then
            LogErr "Failed to install the CUAD toolkit $CudaToolkitVersion!"
            SetTestStateAborted
            exit 1
        fi
    ;;

    ubuntu*)
        GetOSVersion
        CUDA_REPO_PKG="cuda-repo-ubuntu${os_RELEASE//./}_${CUDADriverVersion}_amd64.deb"
        LogMsg "Using ${CUDA_REPO_PKG}"

        wget http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/"${CUDA_REPO_PKG}" -O /tmp/"${CUDA_REPO_PKG}"
        if [ $? -ne 0 ]; then
            LogErr "Failed to download ${CUDA_REPO_PKG}"
            SetTestStateAborted
            exit 1
        fi

        apt-key adv --fetch-keys http://developer.download.nvidia.com/compute/cuda/repos/ubuntu"${os_RELEASE//./}"/x86_64/7fa2af80.pub
        dpkg -i /tmp/"${CUDA_REPO_PKG}"
        dpkg_configure
        apt update
        apt -y --allow-unauthenticated install $CudaToolkitVersion
        if [ $? -ne 0 ]; then
            LogErr "Failed to install the CUAD toolkit $CudaToolkitVersion!"
            SetTestStateAborted
            exit 1
        fi
    ;;
    esac
    LogMsg "Install CUDA toolkit $CudaToolkitVersion successfully."
}

Prepare_Test_Dependencies()
{
    LogMsg "Install dependencies..."
    if [[ "${DISTRO_NAME}" == "debian" ]] || [[ "${DISTRO_NAME}" == "ubuntu" ]] ; then
        dpkg_configure
    fi
    update_repos
    packages=("wget" "python" "git" "python-pip")
    install_package "${packages[@]}"

    # Install all CUDA Toolkit packages required to develop CUDA applications.
    InstallCUDAToolKit

    LogMsg "Install tensorflow-gpu $TensorflowVersion..."
    python -m pip install --upgrade pip
    if [ $TensorflowVersion ]; then
        pip install --upgrade "tensorflow-gpu==$TensorflowVersion"
    else
        pip install --upgrade tf-nightly-gpu
    fi

    LogMsg "Install $CudnnPackage..."
    wget -t 5 "$CudnnPackage" -O cuda.tgz -o download_cudnn.log
    tar -zxf cuda.tgz
    if [ $? -ne 0 ]; then
        LogErr "Install CuDNN $CudnnPackage failed"
        SetTestStateAborted
        exit 1
    fi
    sudo cp -p cuda/lib64/libcudnn* /usr/lib/x86_64-linux-gnu
    if [ $? -ne 0 ]; then
        LogErr "Copy cuda/lib64/libcudnn* to /usr/lib/x86_64-linux-gnu failed"
        SetTestStateAborted
        exit 1
    fi

    echo -e "import tensorflow; print(tensorflow.__version__)" | python
    if [ $? -ne 0 ]; then
        LogErr "Failed to install tensorflow-gpu $TensorflowVersion"
        SetTestStateAborted
        exit 1
    fi

    git clone $BenchmarkTool
    if [ $? -ne 0 ]; then
        LogErr "Get benchmarks tool from $BenchmarkTool failed"
        SetTestStateAborted
        exit 1
    fi
    LogMsg "Install dependencies and tensorflow-gpu finished"
}

Get_Average_Utilization()
{
    timeout=0
    TOTAL_TIMEOUT=300
    while [ $timeout -lt $TOTAL_TIMEOUT ]
    do
        utilizations=$(nvidia-smi --query-gpu=utilization.gpu,utilization.memory --format=csv | sed -n '2p')
        utilization_gpu=$(echo $utilizations  |  awk -F "," '{print $1}' | cut  -d '%' -f1 |sed  's/[[:space:]]//g')
        utilization_mem=$(echo $utilizations  |  awk -F "," '{print $2}' | cut  -d '%' -f1 |sed  's/[[:space:]]//g')
        # Assuming the GPU is working stable once the utilizations of GPU and memory are greater than 30%
        if [[ $utilization_gpu -gt 30 && $utilization_mem -gt 30 ]]; then
            break
        fi
        let timeout++
        sleep 2
    done

    if [ $timeout -ge $TOTAL_TIMEOUT ]; then
        LogErr "The utilizations of GPU and memory are lower than 30% in last $TOTAL_TIMEOUT seconds."
        return 1
    fi

    timeout=0
    utilization_gpu_sum=0
    utilization_mem_sum=0
    while [ $timeout -lt $TOTAL_TIMEOUT ]
    do
        grep "total images/sec" $1 > /dev/null
        if [ $? == 0 ]; then
            break
        fi
        let timeout++
        utilizations=$(nvidia-smi --query-gpu=utilization.gpu,utilization.memory --format=csv | sed -n '2p')
        utilization_gpu=$(echo $utilizations  |  awk -F "," '{print $1}' | cut  -d '%' -f1 |sed  's/[[:space:]]//g')
        utilization_mem=$(echo $utilizations  |  awk -F "," '{print $2}' | cut  -d '%' -f1 |sed  's/[[:space:]]//g')
        let utilization_gpu_sum=utilization_gpu_sum+utilization_gpu
        let utilization_mem_sum=utilization_mem_sum+utilization_mem
        sleep 2
    done

    if [ $timeout -ge $TOTAL_TIMEOUT ]; then
        LogErr "Run GPU benchmarks test timeout"
        return 1
    fi

    let utilization_gpu_avg=utilization_gpu_sum/timeout
    let utilization_mem_avg=utilization_mem_sum/timeout
    echo "Average of gpu and memory utilization: $utilization_gpu_avg $utilization_mem_avg"
}

Run_GPU_Benchmark_Test()
{
    if [ ! -e ${HOME}/test_results ]; then
        mkdir -p "${HOME}/test_results"
    fi
    export PATH=$(ls -d /usr/local/cuda-*)/bin${PATH:+:${PATH}}
    export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
    pushd benchmarks/scripts/tf_cnn_benchmarks
    gpucount=0
    count=$(nvidia-smi --query-gpu=count --id=0 --format=csv)
    for i in $count
    do
       gpucount=$i
    done

    MODES=(inception3 vgg16 alexnet resnet50 resnet152)
    BATCH_SIZE=(32 64 128 512)
    if [ ! -e ${HOME}/test_results ]; then
        mkdir -p "${HOME}/test_results"
    fi

    for mode in "${MODES[@]}"
    do
        for size in "${BATCH_SIZE[@]}"
        do
            LogMsg "Run tensorflow batch_size=${size} model=${mode} data_name=imagenet device=gpu num_gpus=${gpucount}"
            outputName="${HOME}/test_results/${mode}-${size}-${gpucount}-gpu-result.log"
            python tf_cnn_benchmarks.py --local_parameter_device=cpu --batch_size=${size} --model=${mode} --data_name=imagenet --variable_update=parameter_server --distortions=True --device=gpu --data_format=NCHW --forward_only=False --use_fp16=False --num_gpus=${gpucount} 1> $outputName 2>&1 &
            utilizations_arv=$(Get_Average_Utilization $outputName)
            # Wait all GPU processes finished
            gpu_pids=$(nvidia-smi | sed -n 's/|\s*[0-9]*\s*\([0-9]*\)\s*.*/\1/p' | sort | uniq | sed '/^$/d')
            while [ $gpu_pids ]
            do
                gpu_pids=$(nvidia-smi | sed -n 's/|\s*[0-9]*\s*\([0-9]*\)\s*.*/\1/p' | sort | uniq | sed '/^$/d')
                sleep 2
            done
            echo $utilizations_arv >> $outputName
        done
    done
    popd
}

Parse_Result()
{
    LogMsg "Parse test result..."
    pushd "${HOME}"/test_results
    csv_file=tensorflowBenchmark.csv
    csv_file_tmp=output_tmp.csv
    rm -rf $csv_file
    echo "batch_size,model,num_gpus,total_images_sec,utilization_mem_avg,utilization_gpu_avg" > $csv_file_tmp
    result_list=($(ls *gpu-result.log))
    count=0
    while [ "x${result_list[$count]}" != "x" ]
    do
        file_name=${result_list[$count]}
        echo "The file $file_name is parsing..."
        model=$(echo "$file_name" | tr '-' " " | awk '{print $1}')
        batch_size=$(echo "$file_name" | tr '-' " " | awk '{print $2}')
        num_gpus=$(echo "$file_name" | tr '-' " " | awk '{print $3}')
        total_images_sec=$(grep "total images/sec" "$file_name" | tr ":" " " | awk '{print $NF}')
        utilization_gpu_avg=$(grep "gpu and memory utilization" "$file_name" | tr ":" " " | awk '{print $(NF-1)}')
        utilization_mem_avg=$(grep "gpu and memory utilization" "$file_name" | tr ":" " " | awk '{print $NF}')
        echo "$batch_size,$model,$num_gpus,$total_images_sec,$utilization_mem_avg,$utilization_gpu_avg" >> $csv_file_tmp
        ((count++))
    done

    cat $csv_file_tmp > $csv_file
    rm -rf $csv_file_tmp
    LogMsg "Parse test result completed"
    cp $csv_file "$HOME"
    popd
}

#######################################################################
#
# Main script body
#
#######################################################################
# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

UtilsInit
collect_VM_properties
Prepare_Test_Dependencies
SetTestStateRunning
Run_GPU_Benchmark_Test
Parse_Result
tar czf test_results.tar.gz ${HOME}/test_results
SetTestStateCompleted
exit 0