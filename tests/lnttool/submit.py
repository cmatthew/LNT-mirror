# RUN: rm -rf %t.instance
# RUN: python %{shared_inputs}/create_temp_instance.py \
# RUN:   %s %{shared_inputs}/SmallInstance %t.instance
# RUN: %{shared_inputs}/server_wrapper.sh %t.instance 9091 \
# RUN:    lnt submit "http://localhost:9091/db_default/submitRun" --commit=1 \
# RUN:       %{shared_inputs}/sample-report.json | \
# RUN:    FileCheck %s --check-prefix=CHECK-DEFAULT
#
# CHECK-DEFAULT: http://localhost:9091/db_default/v4/nts/3
#
# RUN: rm -rf %t.instance
# RUN: python %{shared_inputs}/create_temp_instance.py \
# RUN:   %s %{shared_inputs}/SmallInstance %t.instance
# RUN: %{shared_inputs}/server_wrapper.sh %t.instance 9091 \
# RUN:    lnt submit "http://localhost:9091/db_default/submitRun" --commit=1 \
# RUN:       %{shared_inputs}/sample-report.json -v | \
# RUN:    FileCheck %s --check-prefix=CHECK-VERBOSE
#
# CHECK-VERBOSE: Import succeeded.
# CHECK-VERBOSE: --- Tested: 10 tests --
#
# CHECK-VERBOSE: Imported Data
# CHECK-VERBOSE: -------------
# CHECK-VERBOSE: Added Machines: 1
# CHECK-VERBOSE: Added Runs    : 1
# CHECK-VERBOSE: Added Tests   : 2
#
# CHECK-VERBOSE: Results
# CHECK-VERBOSE: ----------------
# CHECK-VERBOSE: PASS : 10
# CHECK-VERBOSE: Results available at: http://localhost:9091/db_default/v4/nts/3

# RUN: rm -rf %t.instance
# RUN: python %{shared_inputs}/create_temp_instance.py \
# RUN:   %s %{shared_inputs}/SmallInstance %t.instance
# RUN: %{shared_inputs}/server_wrapper.sh %t.instance 9091 \
# RUN:    lnt submit "http://localhost:9091/db_default/submitRun" --commit=1 \
# RUN:       %{src_root}/docs/report-example.json -v | \
# RUN:    FileCheck %s --check-prefix=CHECK-NEWFORMAT
#
# CHECK-NEWFORMAT: Import succeeded.
# CHECK-NEWFORMAT: --- Tested: 10 tests --
#
# CHECK-NEWFORMAT: Imported Data
# CHECK-NEWFORMAT: -------------
# CHECK-NEWFORMAT: Added Machines: 1
# CHECK-NEWFORMAT: Added Runs    : 1
# CHECK-NEWFORMAT: Added Tests   : 2
#
# CHECK-NEWFORMAT: Results
# CHECK-NEWFORMAT: ----------------
# CHECK-NEWFORMAT: PASS : 10
# CHECK-NEWFORMAT: Results available at: http://localhost:9091/db_default/v4/nts/3
#
# RUN: rm -rf %t.instance
# RUN: python %{shared_inputs}/create_temp_instance.py \
# RUN:   %s %{shared_inputs}/SmallInstance %t.instance
# RUN: %{shared_inputs}/server_wrapper.sh %t.instance 9091 \
# RUN:   lnt submit "http://localhost:9091/db_default/v4/compile/submitRun" \
# RUN:   --commit=1 %S/Inputs/compile_submission.json -v \
# RUN:   | FileCheck %s --check-prefix=CHECK-OLDFORMAT-COMPILE
#
# CHECK-OLDFORMAT-COMPILE: --- Tested: 10 tests --
#
# CHECK-OLDFORMAT-COMPILE: Imported Data
# CHECK-OLDFORMAT-COMPILE: -------------
# CHECK-OLDFORMAT-COMPILE: Added Machines: 1
# CHECK-OLDFORMAT-COMPILE: Added Runs    : 1
# CHECK-OLDFORMAT-COMPILE: Added Tests   : 2
#
# CHECK-OLDFORMAT-COMPILE: Results
# CHECK-OLDFORMAT-COMPILE: ----------------
# CHECK-OLDFORMAT-COMPILE: PASS : 10
# CHECK-OLDFORMAT-COMPILE: Results available at: http://localhost:9091/db_default/v4/compile/5
