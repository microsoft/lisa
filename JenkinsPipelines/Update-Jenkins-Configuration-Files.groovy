// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the Apache License.
//This script requires following parameters to be added in Jenkins job.
//Example:  
//GitBranch = https://github.com/LIS/LISAv2.git 
//GitRepo = master 
//MenuFilesPath = "Shared directory between jenkins master and slave" 

stage("Update Jenkins Menu")
{
    node("azure")
    {
        git branch: "${GitBranch}", url: "${GitRepo}"
        powershell(".\\JenkinsPipelines\\Scripts\\JenkinsTestSelectionMenuGenerator.ps1 -DestinationPath '${MenuFilesPath}'")    
    }
}