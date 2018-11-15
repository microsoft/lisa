param (
    [switch] $Detailed,
    [string] $FilesToTrack,
    [string] $From,
    [string] $Till,
    [string] $before,
    [string] $after
)

if ($before -imatch "today")
{
    $before = Get-Date -Format "yyyy-MM-dd"
}
$CommitCounter = 1
foreach ($file in $FilesToTrack.Split(';'))
{
    Write-Host $file
}

cd .\linux-next

if ( -not $before -and -not $after -and $From -and $Till )
{
    git reset --hard
    #region Get 'From' Commits
    Write-Host "Checking out $From"
    git checkout --force $From
    foreach ($file in $FilesToTrack.Split(';'))
    {
        if ($file)
        {
            $FileName = $file | Split-Path -Leaf
            Write-Host "Getting 'From' commits from $FileName"
            git log --pretty=format:"%H -=- %s -=- %cd" $file > "..\$FileName-from.txt"
        }
    }
    #endregion

    #region Get 'Till' Commits
    Write-Host "Checking out $Till"
    git checkout --force $till
    foreach ($file in $FilesToTrack.Split(';'))
    {
        if ($file)
        {
            $FileName = $file | Split-Path -Leaf
            Write-Host "Getting 'Till' commits from $FileName"
            git log --pretty=format:"%H -=- %s -=- %an -=- %cd" $file > "..\$FileName-till.txt"
        }
    }
    #endregion
    #>
    Write-Host "---------------------------Results---------------------------"
    foreach ($file in $FilesToTrack.Split(';'))
    {
        if ($file)
        {
            try {
                $FileName = $file | Split-Path -Leaf
                $compare = Compare-Object -ReferenceObject $(Get-Content "..\$FileName-till.txt") -DifferenceObject $(Get-Content "..\$FileName-from.txt")
                if ($compare) {
                    foreach ($obj in $compare) {
                        $line = "$($obj.InputObject)"
                        $CommitID =  ($line -split ' -=- ')[0]
                        $CommitSubject = ($line -split ' -=- ')[1]
                        $CommitAuthor = ($line -split ' -=- ')[2]
                        $CommitDate = ($line -split ' -=- ')[3]

                        if ($Detailed){
                            $GitOut = git log -1 $CommitID
                            Write-Host "$CommitCounter." -NoNewline
                            foreach ($newline in $GitOut -split "`n") {
                                Write-Host "`t$newline"
                            }
                        }
                        else {
                            Write-Host "$CommitCounter.`t$CommitID"
                            Write-Host "`tFile:    $file"
                            Write-Host "`tSubject: $CommitSubject"
                            Write-Host "`tAuthor:  $CommitAuthor"
                            Write-Host "`tDate:    $CommitDate"
                        }
                        Write-Host ""
                        $CommitCounter += 1
                    }
                }
            }
            catch {

            }
        }
    }
}
if ( $before -and $after -and  -not $From -and -not $Till )
{
    foreach ($file in $FilesToTrack.Split(';'))
    {
        if ($file)
        {
            $FileName = $file | Split-Path -Leaf
            Write-Host "Getting commits after '$after' and before '$before' from $FileName"
            git log --after $after --before $before --pretty=format:"%H -=- %s -=- %an -=- %cd" $file > "..\$FileName-$before-$after.txt"
        }
    }

    Write-Host "---------------------------Results---------------------------"
    foreach ($file in $FilesToTrack.Split(';'))
    {
        if ($file)
        {
            try {

                $FileName = $file | Split-Path -Leaf
                $FileContents = $null
                $FileContents = Get-Content "..\$FileName-$before-$after.txt"
                if ($FileContents)
                {
                    foreach ($line in $FileContents) {
                        $CommitID =  ($line -split ' -=- ')[0]
                        $CommitSubject = ($line -split ' -=- ')[1]
                        $CommitAuthor = ($line -split ' -=- ')[2]
                        $CommitDate = ($line -split ' -=- ')[3]

                        if ($Detailed){
                            $GitOut = git log -1 $CommitID
                            Write-Host "$CommitCounter." -NoNewline
                            foreach ($newline in $GitOut -split "`n") {
                                Write-Host "`t$newline"
                            }
                        }
                        else {
                            Write-Host "$CommitCounter.`t$CommitID"
                            Write-Host "`tFile:    $file"
                            Write-Host "`tSubject: $CommitSubject"
                            Write-Host "`tAuthor:  $CommitAuthor"
                            Write-Host "`tDate:    $CommitDate"
                        }
                        Write-Host ""
                        $CommitCounter += 1
                    }
                }
            }
            catch {
            }
        }
    }
}
