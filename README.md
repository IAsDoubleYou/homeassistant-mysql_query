# homeassistant-mysql_query
A Home Assistant custom component that creates a ResponseData service to execute a query against a MySQL server.. The result values become available as an iterable data structure.

Query should be written in the form:

`select col1, col2, .... from table where condition`

<b>examples</b>:<br>
`  select * from contacts`<br>
`  select name, phonenumber from contacts`

<b>Configuration:</b><br>
The MySQL database configuration should be added as follow in configuration.yaml:

`mysql_query:`<br>
`  mysql_host: <mysqldb host ip address>`<br>
`  mysql_username: <mysqldb username>`<br>
`  mysql_password: <mysqldb password>`<br>
`  mysql_db: <mysqldb databasename>`<br>
