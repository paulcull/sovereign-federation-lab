package bank.migration
import rego.v1
default allow := false
allow if { input.operation == "register"; input.country == "IN" }
allow if { input.operation == "transfer"; input.country == "IN"; input.elapsed < input.deadline; input.conflict == false }
allow if { input.operation in {"read","write"}; input.country == "SG"; input.elapsed < input.deadline }
allow if { input.operation in {"read","write"}; input.country == "IN"; input.conflict == false }
allow if { input.operation == "purge"; input.country == "SG"; input.home == "IN" }
