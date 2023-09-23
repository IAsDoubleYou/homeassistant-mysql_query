# homeassistant-mysql_query
A Home Assistant custom component that creates a ResponseData service to execute a query against a MySQL server.. The result values become available as an iterable data structure.

Query should be written in the form:
select <columns>|* from <table> [where <condition>]
examples:
  select * from contacts
  select name, phonenumber from contacts
