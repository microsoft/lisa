#region Access Server Methods
function ConnectAccessDB ($dbFilePath) {
	
	# Test to ensure valid path to database file was supplied
	if (-not (Test-Path $dbFilePath)) {
		Write-Error "Invalid Access database path specified. Please supply full absolute path to database file!"
	}
	
	# TO-DO: Add check to ensure file is either MDB or ACCDB
	
	# Create a new ADO DB connection COM object, which will give us useful methods & properties such as "Execute"!
	$AccessConnection = New-Object -ComObject ADODB.Connection
	
	# Access 00-03 (MDB) format has a different connection string than 2007
	if ((Split-Path $dbFilePath -Leaf) -match [regex]"\.mdb$") {
		Write-Host "Access 2000-2003 format (MDB) detected!  Using Microsoft.Jet.OLEDB.4.0."
		$AccessConnection.Open("Provider = Microsoft.Jet.OLEDB.4.0; Data Source= $dbFilePath")
		return $AccessConnection
	}
	
	# Here's the check for if 2007 connection is necessary
	if ((Split-Path $dbFilePath -Leaf) -match [regex]"\.accdb$") {
		Write-Host "Access 2007 format (ACCDB) detected!  Using Microsoft.Ace.OLEDB.12.0."
		$AccessConnection.Open("Provider = Microsoft.Ace.OLEDB.12.0; Persist Security Info = False; Data Source= $dbFilePath")
		return $AccessConnection
	} 

}

Function ConnectSqlDB ($dbServer,$dbName)
{
	$SQLServer = $dbServer #use Server\Instance for named SQL instances! 
	$SQLDBName = $dbName
	$SqlQuery = "select * from authors WHERE Name = 'John Simon'"

	$SqlConnection = New-Object System.Data.SqlClient.SqlConnection
	$SqlConnection.ConnectionString = "Server = $SQLServer; Database = $SQLDBName; Integrated Security = True"
	return $SqlConnection
#	$SqlCmd = New-Object System.Data.SqlClient.SqlCommand
#	$SqlCmd.CommandText = $SqlQuery
#	$SqlCmd.Connection = $SqlConnection
#
#	$SqlAdapter = New-Object System.Data.SqlClient.SqlDataAdapter
#	$SqlAdapter.SelectCommand = $SqlCmd
#
#	$DataSet = New-Object System.Data.DataSet
#	$SqlAdapter.Fill($DataSet)
#	$SqlConnection.Close()
}

function OpenAccessRecordSet ($conn,$sqlQuery) {

	# Ensure SQL query isn't null
	if ($SqlQuery.length -lt 1) {
		Throw "Please supply a SQL query for the recordset selection!"
	}
	
	# Variables used for the connection itself.  Leave alone unless you know what you're doing.
	$adOpenStatic = 3
	$adLockOptimistic = 3
	
	# Create the recordset object using the ADO DB COM object
	$AccessRecordSet = New-Object -ComObject ADODB.Recordset
	
	# Finally, go and get some records from the DB!
	$AccessRecordSet.Open($sqlQuery, $conn, $adOpenStatic, $adLockOptimistic)
	return $AccessRecordSet
}

function ExecuteAccessSQLStatement ($conn,$query) {
	$conn.Execute($query)
}

function CloseAccessRecordSet ($recordSet) {
	$recordSet.Close()
}

function DisconnectAccessDB ($conn) {
	$conn.Close()
}

function AddRecord ($recordSet, [string] $field, [string] $value)
{
	$recordSet.AddNew()
	$recordSet.Fields.Item($field).Value = $value
	$recordSet.Update()
}
#endregion

#region Sql Server Methods

Function ConnectSqlDB
{
	param
	(
	[Parameter(Position=0, Mandatory=$true)] [string]$sqlServer,
	[Parameter(Position=1, Mandatory=$true)] [string]$sqlDBName
	)
	$sqlConn = New-Object System.Data.SqlClient.SqlConnection
	$sqlConn.ConnectionString = "Server = $sqlServer; Database = $sqlDBName; Integrated Security = True"
	$sqlConn.open()
	return $sqlConn
}

Function ExecuteSqlStatement
{
	param
	(
    [Parameter(Position=0, Mandatory=$true)] $sqlConn,
    [Parameter(Position=1, Mandatory=$true)] [string]$sqlQuery
    )
	$sqlCmd = New-Object System.Data.SqlClient.SqlCommand
	$sqlCmd.connection = $sqlConn
	$sqlCmd.CommandText = $SqlQuery
	$sqlCmd.ExecuteNonQuery()
}

Function GetSqlQueryResult
{
#Its Incomplete
	param
	(
    [Parameter(Position=0, Mandatory=$true)] $sqlConn,
    [Parameter(Position=1, Mandatory=$true)] [string]$sqlQuery,
	[Parameter(Position=2,Mandatory=$false)] [switch] $scaler
    )
	$sqlCmd = New-Object System.Data.SqlClient.SqlCommand
	$sqlCmd.connection = $sqlConn
	$SqlCmd.CommandText = $SqlQuery
	if ($scaler)
	{
		$result = $sqlCmd.ExecuteScalar()
	}
	return $result
#	$ds=New-Object system.Data.DataSet
#	$da=New-Object system.Data.SqlClient.SqlDataAdapter($cmd)
#	$da.fill($ds) | Out-Null
#	$ds.Tables[0]	
}

function DisconnectSqlDB ($conn) {
	$conn.Close()
}
#endregion