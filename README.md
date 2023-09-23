# homeassistant-mysql_query
A Home Assistant custom component that creates a ResponseData service to execute a query against a MySQL server.. The result values become available as an iterable data structure.

Query should be written in the form:

select col1, col2, .... from table where condition

examples:
  select * from contacts

  select name, phonenumber from contacts


Configuration:
The MySQL database configuration should be added as follow in configuration.yaml:

`mysql_query:`<br>
`  mysql_host: <mysqldb host ip address>`
`  mysql_username: <mysqldb username>`
`  mysql_password: <mysqldb password>`
`  mysql_db: <mysqldb databasename>`
