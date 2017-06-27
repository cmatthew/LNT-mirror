# REQUIRES: postgres
# RUN: rm -rf "%t.install"
# RUN: %{shared_inputs}/postgres_wrapper.sh "%t.install" /bin/sh %s "%t.install" postgresql://pgtest@localhost:9100 "%{shared_inputs}"
set -eux

TESTDIR="$1"
PGURL="$2"
SHARED_INPUTS="$3"
dropdb --if-exists --maintenance-db="${PGURL}/postgres" lnt_regr_test_PostgresDB
createdb --maintenance-db="${PGURL}/postgres" lnt_regr_test_PostgresDB

lnt create "${TESTDIR}/instance" --db-dir ${PGURL} --default-db lnt_regr_test_PostgresDB

# Import a test set.
lnt import "${TESTDIR}/instance" "${SHARED_INPUTS}/sample-a-small.plist" --commit=1 --show-sample-count

# Import a test set.
lnt import "${TESTDIR}/instance" "${SHARED_INPUTS}/sample-a-small.plist" --commit=1 --show-sample-count

# Check that we remove both the sample and the run, and that we don't commit by
# default.
#
lnt updatedb "${TESTDIR}/instance" --testsuite nts --delete-run 1 \
	--show-sql > "${TESTDIR}/runrm.out"
# RUN: FileCheck --check-prefix CHECK-RUNRM %s < "%t.install/runrm.out"

# CHECK-RUNRM: DELETE FROM "NT_Sample" WHERE "NT_Sample"."RunID" IN (%(RunID_1)s)
# CHECK-RUNRM-NEXT: {'RunID_1': 1}
# CHECK-RUNRM: DELETE FROM "NT_Run" WHERE "NT_Run"."ID" IN (%(ID_1)s)
# CHECK-RUNRM-NEXT: {'ID_1': 1}
# CHECK-RUNRM: ROLLBACK

# Check that we remove runs when we remove a machine.
#
lnt updatedb "${TESTDIR}/instance" --testsuite nts \
	--delete-machine "LNT SAMPLE MACHINE" --commit=1 \
	--show-sql > "${TESTDIR}/machinerm.out"
# RUN: FileCheck --check-prefix CHECK-MACHINERM %s < "%t.install/machinerm.out"

# CHECK-MACHINERM: DELETE FROM "NT_Sample" WHERE "NT_Sample"."RunID" IN (%(RunID_1)s)
# CHECK-MACHINERM-NEXT: {'RunID_1': 1}
# CHECK-MACHINERM: DELETE FROM "NT_Run" WHERE "NT_Run"."ID" IN (%(ID_1)s)
# CHECK-MACHINERM-NEXT: {'ID_1': 1}
# CHECK-MACHINERM: DELETE FROM "NT_Machine" WHERE "NT_Machine"."Name" = %(Name_1)s
# CHECK-MACHINERM-NEXT: {'Name_1': 'LNT SAMPLE MACHINE'}
# CHECK-MACHINERM: COMMIT
