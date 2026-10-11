package bank.migration_test
import rego.v1
import data.bank.migration.allow
base := {"operation":"transfer","country":"IN","elapsed":0,"deadline":600,"conflict":false,"home":"SG"}
test_transfer_before_deadline if { allow with input as base }
test_deadline_blocks_transfer if { not allow with input as object.union(base,{"elapsed":600}) }
test_us_exclusion if { not allow with input as object.union(base,{"country":"US"}) }
test_record_conflict if { not allow with input as object.union(base,{"conflict":true}) }
test_unknown_operation if { not allow with input as object.union(base,{"operation":"unknown"}) }
test_sg_write_window if { allow with input as object.union(base,{"operation":"write","country":"SG"}) }
test_sg_expired_read if { not allow with input as object.union(base,{"operation":"read","country":"SG","elapsed":600}) }
test_india_write_after_deadline if { allow with input as object.union(base,{"operation":"write","elapsed":600,"home":"IN"}) }
test_india_excluded_write if { not allow with input as object.union(base,{"operation":"write","conflict":true}) }
test_purge_requires_new_home if { not allow with input as object.union(base,{"operation":"purge","country":"SG"}) }
test_purge_after_cutover if { allow with input as object.union(base,{"operation":"purge","country":"SG","home":"IN","elapsed":600}) }
test_missing_input if { not allow with input as {} }
