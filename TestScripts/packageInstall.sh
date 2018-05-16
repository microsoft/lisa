#!/bin/bash
#V-SHISAV@MICROSOFT.COM

#HOW TO PARSE THE ARGUMENTS.. SOURCE - http://stackoverflow.com/questions/4882349/parsing-shell-script-arguments

while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done
packageName=$install
isRemote=$isRemote
isLocal=$isLocal
fileName=$file
CurrentDate=`date`

installFromFolder()
{
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done
sourceFolder=$sourceFolder
cd $sourceFolder
ls
if [ -e ./configure ]; then
    chmod +x configure && ./configure && make && make install
    exitVal=$?
elif [ -e ./setup.py ]; then
    python setup.py build && python setup.py install
    exitVal=$?
fi
cd ..
return $exitVal
}

getFolderName()
{
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

compressedFile=$compressedFile
if [[ "$compressedFile" == *.tar.gz ]]; then
    folderName=${compressedFile%.tar.gz*}
elif [[ "$compressedFile" == *.tar ]]; then
    folderName=${compressedFile%.tar.bz2*}
elif [[ "$compressedFile" == *.tar ]]; then
    folderName=${compressedFile%.tar*}
fi
echo $folderName
}

installFromCompressedFile()
{
#{
#   extract the source code.
#   invoke : decompressFile -file $fileName
#   search for installation files in extracted folder. Like - setup.py / configure / make etc.
#   invoke "appropriate" installation method.. [installPythonSourceCode() / installMakeSourceCode() / ...]
#   return exit code.
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

compressedFile=$compressedFile
decompressFile -fileToDecompress $compressedFile
installFolder=`getFolderName -compressedFile $compressedFile`
echo "$installFolder"
installFromFolder -sourceFolder $installFolder
exitVal=$?

return $exitVal
}

decompressFile()
{
#   determine the extraction method depending on *.tar, *.tar.gz, *.bz2, *.gzip etc.
#   execute : tar -xzf / gunzip / bzip etc. and untar the compressed file.
#   return exit code.
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

fileToDecompress=$fileToDecompress
if [[ "$installFile" == *.tar ]]; then
    tar -xzvf $fileToDecompress
        #installFromCompressedFile
    exitVal=$?
elif [[ "$installFile" == *.tar.gz ]]; then
    tar -xvf $fileToDecompress
    exitVal=$?
fi

if [ $exitVal == 0 ]; then
    echo "Decompresssion Successfull"
else
    echo "Decompresssion Failed"
fi
return $exitVal

}
#other installation methods support can be added depending on requirement.

installLocalFile()
{
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done

installFile=$LocalFile
if [[ ( "$installFile" == *.tar ) || ( "$installFile" == *.tar.gz ) || ( "$installFile" == *.tar.bz2 ) ]]; then
    echo "provided file $installFile"
    echo "Installing from copressed file"
    installFromCompressedFile -compressedFile $installFile
    exitVal=$?
elif [[ "$installFile" == *.rpm ]]; then
    echo "provided file $installFile"
    echo "Installing rpm file"
    rpm -ivh $installFile
    exitVal=$?
elif [[ "$installFile" == *.deb ]]; then
    echo "provided file $installFile"
    echo "Installing deb file"
    dpkg -i $installFile
    exitVal=$?
elif [[ "$installFile" == *.sh ]]; then
    echo "provided file $installFile"
    echo "Executing shell script ..."
    chmod +x $installFile
	dos2unix $installFile
    ./$installFile
    exitVal=$?
elif [ -z $installFile ]; then
    echo "Please provide file with -file <filename> argument"
    exitVal=1
else
    echo "Unknowin file type.."
    exitVal=1
fi
return $exitVal
}
installRemotePackage()
{
while echo $1 | grep ^- > /dev/null; do
    eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
    shift
    shift
done
packageName=$install
        if [ -e /etc/debian_version ]; then
                apt-get install --force-yes -y $packageName
                installStatus=$?
                if [ $installStatus = 0 ]; then
                        echo "Install $packageName : InstallSuccess"
                        exitVal=0
                else
                        echo "Install $packageName : FAILED"
                        exitVal=1
                fi
        fi
        if [ -e /etc/redhat-release ]; then
                sed -i 's/exclude=kernel/#exclude=kernel/' /etc/yum.conf
                yum install --nogpgcheck -y $packageName
                installStatus=$?
                if [ $installStatus = "0" ]; then
                        echo "Install $packageName : InstallSuccess"
                        exitVal=0
                else
                        echo "Install $packageName : FAILED"
                        exitVal=1
                fi
        fi
        if [ -e /etc/SuSE-release ]; then
                zypper --non-interactive --no-gpg-checks install $packageName
                installStatus=$?
                if [ $installStatus = "0" ]; then
                        echo "Install $packageName : InstallSuccess"
                        exitVal=0
                else
                        echo "Install $packageName : FAILED"
                        exitVal=1
                fi
        fi
return $exitVal
}
updateDistro()
{
    if [ -e /etc/debian_version ]; then
        apt-get --force-yes -y update
        installStatus=$?
        if [ $installStatus = 0 ]; then
            echo "Install Update : InstallSuccess"
            exitVal=0
        else
        echo "Install Update : FAILED"
        exitVal=1
        fi
    fi
    if [ -e /etc/redhat-release ]; then
            sed -i 's/exclude=kernel/#exclude=kernel/' /etc/yum.conf
        yum --nogpgcheck -y update
        installStatus=$?
        if [ $installStatus = "0" ]; then
            echo "Install Update : InstallSuccess"
            exitVal=0
        else
            echo "Install Update : FAILED"
            exitVal=1
        fi
    fi
    if [ -e /etc/SuSE-release ]; then
        zypper --non-interactive --no-gpg-checks update
        installStatus=$?
        if [ $installStatus = "0" ]; then
            echo "Updated successfully.."
            exitVal=0
        else
            echo "Update failed.."
            exitVal=1
        fi
    fi

return $exitVal
}

# main body starts here..

if [ "$packageName" = "UpdateCurrentDistro" ]; then
    updateDistro
    installStatus=$?
    if [ $installStatus = "0" ]; then
        echo "Install $packageName : InstallSuccess"
        exitVal=0
    else
        echo "Install $packageName  : FAILED"
        exitVal=1
    fi

    exit $exitVal
else
    if [ -z $packageName ]; then
        echo "No packages are given to install. Please use -package <Package Name>"
        exitVal=0
    else
        if [ -z $isLocal ]; then
            echo "Please mention -isLocal yes/no"
        elif [ "$isLocal" = "no" ]; then
                installRemotePackage -install $packageName
                exitVal=$?
        elif [ "$isLocal" = "yes" ]; then
                installLocalFile -LocalFile $fileName
				installStatus=$?
                if [ $installStatus = "0" ]; then
                    echo "Install $packageName : InstallSuccess"
                    exitVal=0
                else
                    echo "Install packageName : FAILED"
                    exitVal=1
                fi
        else
            echo "Please provide -isLocal yes or -isLocal no [CaSe SensitivE]"
        fi
    fi
fi
exit $exitVal

