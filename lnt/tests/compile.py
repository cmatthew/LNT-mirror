import errno
import hashlib
import json
import os
import platform
import pprint
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

import lnt.testing
import lnt.testing.util.compilers
from lnt.testing.util.commands import note, warning, error, fatal
from lnt.testing.util.commands import capture, mkdir_p, rm_f
from lnt.testing.util.misc import TeeStream, timestamp
from lnt.testing.util import machineinfo

# Interface to runN.
#
# FIXME: Simplify.
#
# FIXME: Figure out a better way to deal with need to run as root. Maybe farm
# memory sampling process out into something we can setuid? Eek.
def runN(args, N, cwd, preprocess_cmd=None, env=None, sample_mem=False,
         ignore_stderr=False, stdout=None, stderr=None):
    cmd = ['runN', '-a']
    if sample_mem:
        cmd = ['sudo'] + cmd + ['-m']
    if preprocess_cmd is not None:
        cmd.extend(('-p', preprocess_cmd))
    if stdout is not None:
        cmd.extend(('--stdout', stdout))
    if stderr is not None:
        cmd.extend(('--stderr', stderr))
    cmd.append(str(int(N)))
    cmd.extend(args)

    if opts.verbose:
        print >>test_log, "running: %s" % " ".join("'%s'" % arg
                                                   for arg in cmd)
    p = subprocess.Popen(args=cmd,
                         stdin=None,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         env=env,
                         cwd=cwd)
    stdout,stderr = p.communicate()
    res = p.wait()

    data = None
    try:
        data = eval(stdout)
    except:
        error("failed to parse output: %s\n" % stdout)

    if not ignore_stderr and stderr.strip():
        error("stderr isn't empty: %s\n" % stderr)
        data = None

    if res:
        error("res != 0: %s\n" % res)
        data = None

    return data

# Test functions.
def get_input_path(opts, *names):
    return os.path.join(opts.test_suite_externals, "lnt-compile-suite-src",
                        *names)

def get_output_path(*names):
    return os.path.join(g_output_dir, *names)

def get_runN_test_data(name, variables, cmd, ignore_stderr=False,
                       sample_mem=False, only_mem=False,
                       stdout=None, stderr=None, preprocess_cmd=None):
    if only_mem and not sample_mem:
        raise ArgumentError,"only_mem doesn't make sense without sample_mem"

    data = runN(cmd, variables.get('run_count'), cwd='/tmp',
                ignore_stderr=ignore_stderr, sample_mem=sample_mem,
                stdout=stdout, stderr=stderr, preprocess_cmd=preprocess_cmd)
    if data is not None:
        if data.get('version') != 0:
            raise ValueError,'unknown runN data format'
        data_samples = data.get('samples')
    keys = []
    if not only_mem:
        keys.extend([('user',1),('sys',2),('wall',3)])
    if sample_mem:
        keys.append(('mem',4))
    for key,idx in keys:
        tname = '%s.%s' % (name,key)
        success = False
        samples = []
        if data is not None:
            success = True
            samples = [sample[idx] for sample in data_samples]
        yield (success, tname, samples)

# FIXME: Encode dependency on output automatically, for simpler test execution.
def test_cc_command(base_name, run_info, variables, input, output, flags,
                    extra_flags, has_output=True, ignore_stderr=False,
                    can_memprof=True):
    name = '%s/(%s)' % (base_name,' '.join(flags),)
    input = get_input_path(opts, input)
    output = get_output_path(output)

    cmd = [variables.get('cc')]
    cmd.extend(extra_flags)
    cmd.append(input)
    cmd.extend(flags)

    # FIXME: Probably a bad idea, but its not worth worry about test failures
    # for compiler versions which emit warnings on the test inputs for now.
    cmd.append('-w')

    # Do a memory profiling run, if requested.
    #
    # FIXME: Doing this as a separate step seems silly. We shouldn't do any
    # extra run just to get the memory statistics.
    if can_memprof and opts.memory_profiling:
        # Find the cc1 command, which we use to do memory profiling. To do this
        # we execute the compiler with '-###' to figure out what it wants to do.
        cc_output = capture(cmd + ['-o','/dev/null','-###'],
                            include_stderr=True).strip()
        cc_commands = []
        for ln in cc_output.split('\n'):
            # Filter out known garbage.
            if (ln == 'Using built-in specs.' or
                ln.startswith('Configured with:') or
                ln.startswith('Target:') or
                ln.startswith('Thread model:') or
                ' version ' in ln):
                continue
            cc_commands.append(ln)

        if len(cc_commands) != 1:
            fatal('unable to determine cc1 command: %r' % cc_output)

        cc1_cmd = shlex.split(cc_commands[0])
        for res in get_runN_test_data(name, variables, cc1_cmd,
                                      ignore_stderr=ignore_stderr,
                                      sample_mem=True, only_mem=True):
            yield res

    rm_f(output)
    for res in get_runN_test_data(name, variables, cmd + ['-o',output],
                                  ignore_stderr=ignore_stderr):
        yield res

    # If the command has output, track its size.
    if has_output:
        tname = '%s.size' % (name,)
        success = False
        samples = []
        try:
            stat = os.stat(output)
            success = True

            # For now, the way the software is set up things are going to get
            # confused if we don't report the same number of samples as reported
            # for other variables. So we just report the size N times.
            #
            # FIXME: We should resolve this, eventually.
            for i in range(variables.get('run_count')):
                samples.append(stat.st_size)
        except OSError,e:
            if e.errno != errno.ENOENT:
                raise
        yield (success, tname, samples)

def test_compile(name, run_info, variables, input, output, pch_input,
                 flags, stage, extra_flags=[]):
    extra_flags = list(extra_flags)

    cc_name = variables.get('cc_name')
    is_llvm = not (cc_name == 'gcc')
    is_clang = not (cc_name in ('gcc', 'llvm-gcc'))

    # Ignore irgen stages for non-LLVM compilers.
    if not is_llvm and stage in ('irgen', 'irgen_only',):
        return ()

    # Ignore 'init' and 'irgen_only' stages for non-Clang.
    if not is_clang and stage in ('init', 'irgen_only'):
        return ()

    # Force gnu99 mode for all compilers.
    if not is_clang:
        extra_flags.append('-std=gnu99')

    stage_flags,has_output = { 'pch-gen' : (('-x','objective-c-header'),True),
                               'driver' : (('-###','-fsyntax-only'), False),
                               'init' : (('-fsyntax-only',
                                          '-Xclang','-init-only'),
                                         False),
                               'syntax' : (('-fsyntax-only',), False),
                               'irgen_only' : (('-emit-llvm','-c',
                                                '-Xclang','-emit-llvm-only'),
                                               False),
                               'irgen' : (('-emit-llvm','-c'), True),
                               'codegen' : (('-S',), True),
                               'assembly' : (('-c',), True), }[stage]

    # Ignore stderr output (instead of failing) in 'driver' stage, -### output
    # goes to stderr by default.
    ignore_stderr = stage == 'driver'

    # We can't memory profile an assembly command.
    #
    # FIXME: Actually, we can with -integrated-as.
    can_memprof = stage != 'assembly'

    extra_flags.extend(stage_flags)
    if pch_input is not None:
        assert pch_input.endswith('.gch')
        extra_flags.extend(['-include', get_output_path(pch_input[:-4])])

    extra_flags.extend(['-I', os.path.dirname(get_input_path(opts, input))])

    return test_cc_command(name, run_info, variables, input, output, flags,
                           extra_flags, has_output, ignore_stderr, can_memprof)

def test_build(base_name, run_info, variables, project, num_jobs):
    name = '%s(j=%d)' % (base_name, num_jobs)
    # Check if we need to expand the archive into the sandbox.
    archive_path = get_input_path(opts, project['archive'])
    with open(archive_path) as f:
        archive_hash = hashlib.md5(f.read()).hexdigest()

    # Compute the path to unpack to.
    source_path = get_output_path("..", "Sources", project['name'])

    # Load the hash of the last unpack, in case the archive has been updated.
    last_unpack_hash_path = os.path.join(source_path, "last_unpack_hash.txt")
    if os.path.exists(last_unpack_hash_path):
        with open(last_unpack_hash_path) as f:
            last_unpack_hash = f.read()
    else:
        last_unpack_hash = None

    # Unpack if necessary.
    if last_unpack_hash == archive_hash:
        print >>test_log, '%s: reusing sources %r (already unpacked)' % (
            datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), name)
    else:
        # Remove any existing content, if necessary.
        try:
            shutil.rmtree(source_path)
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise

        # Extract the zip file.
        #
        # We shell out to unzip here because zipfile's extractall does not
        # appear to preserve permissions properly.
        mkdir_p(source_path)
        print >>test_log, '%s: extracting sources for %r' % (
            datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), name)
        p = subprocess.Popen(args=['unzip', '-q', archive_path],
                             stdin=None,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             cwd=source_path)
        stdout,stderr = p.communicate()
        if p.wait() != 0:
            fatal(("unable to extract archive %r at %r\n"
                   "-- stdout --\n%s\n"
                   "-- stderr --\n%s\n") % (archive_path, source_path,
                                            stdout, stderr))
        if p.wait() != 0:
            fatal

        # Apply the patch file, if necessary.
        patch_file = project.get('patch_file')
        if patch_file:
            print >>test_log, '%s: applying patch file %r for %r' % (
                datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                patch_file, name)
            patch_file_path = get_input_path(opts, patch_file)
            p = subprocess.Popen(args=['patch', '-i', patch_file_path,
                                       '-p', '1'],
                                 stdin=None,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=source_path)
            stdout,stderr = p.communicate()
            if p.wait() != 0:
                fatal(("unable to apply patch file %r in %r\n"
                       "-- stdout --\n%s\n"
                       "-- stderr --\n%s\n") % (patch_file_path, source_path,
                                                stdout, stderr))

        # Write the hash tag.
        with open(last_unpack_hash_path, "w") as f:
            f.write(archive_hash)

    # Form the test build command.
    build_info = project['build_info']
    if build_info['style'].startswith('xcode-'):
        file_path = os.path.join(source_path, build_info['file'])
        cmd = ['xcodebuild']

        # Add the arguments to select the build target.
        if build_info['style'] == 'xcode-project':
            cmd.extend(('-target', build_info['target'],
                        '-project', file_path))
        elif build_info['style'] == 'xcode-workspace':
            cmd.extend(('-scheme', build_info['scheme'],
                        '-workspace', file_path))
        else:
            fatal("unknown build style in project: %r" % project)

        # Add arguments to ensure output files go into our build directory.
        output_base = get_output_path(name)
        build_base = os.path.join(output_base, 'build')
        cmd.append('OBJROOT=%s' % (os.path.join(build_base, 'obj')))
        cmd.append('SYMROOT=%s' % (os.path.join(build_base, 'sym')))
        cmd.append('DSTROOT=%s' % (os.path.join(build_base, 'dst')))

        # Add additional arguments to force the build scenario we want.
        cmd.extend(('-jobs', str(num_jobs)))
    else:
        fatal("unknown build style in project: %r" % project)

    # Create the output base directory.
    mkdir_p(output_base)

    # Collect the samples.
    print >>test_log, '%s: executing full build: %s' % (
        datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        " ".join("'%s'" % arg
                 for arg in cmd))
    stdout_path = os.path.join(output_base, "stdout.log")
    stderr_path = os.path.join(output_base, "stderr.log")
    # FIXME: I haven't figured out how to prevent Xcode from putting some data
    # (shared PCH files, notably) in the derived data folder. There is most
    # likely a command line setting to override this, but I don't know it
    # yet. Until then, we just blow away the users entire DerivedData folder!
    preprocess_cmd = 'rm -rf "%s" "%s"' % (
        build_base,
        os.path.expanduser("~/Library/Developer/Xcode/DerivedData"))
    for res in get_runN_test_data(name, variables, cmd,
                                  stdout=stdout_path, stderr=stderr_path,
                                  preprocess_cmd=preprocess_cmd):
        yield res

###

def curry(fn, **kw_args):
    return lambda *args: fn(*args, **kw_args)

def get_single_file_tests(flags_to_test):
    all_inputs = [('Sketch/Sketch+Accessibility/SKTGraphicView.m', True, ()),
                  ('403.gcc/combine.c', False, ('-DSPEC_CPU_MACOSX',))]

    stages_to_test = ['driver', 'init', 'syntax', 'irgen_only', 'irgen',
                      'codegen', 'assembly']
    for f in flags_to_test:
        # FIXME: Note that the order matters here, because we need to make sure
        # to generate the right PCH file before we try to use it. Ideally the
        # testing infrastructure would just handle this.
        yield ('pch-gen/Cocoa',
               curry(test_compile, input='Cocoa_Prefix.h',
                     output='Cocoa_Prefix.h.gch', pch_input=None,
                     flags=f, stage='pch-gen'))
        for input,uses_pch,extra_flags in all_inputs:
            name = input
            output = os.path.splitext(os.path.basename(input))[0] + '.o'
            for stage in stages_to_test:
                pch_input = None
                if uses_pch:
                    pch_input = 'Cocoa_Prefix.h.gch'
                yield ('compile/%s/%s' % (name, stage),
                       curry(test_compile, input=input, output=output,
                             pch_input=pch_input, flags=f, stage=stage,
                             extra_flags=extra_flags))

def get_full_build_tests(jobs_to_test, test_suite_externals):
    # Load the project description file from the externals.
    with open(os.path.join(test_suite_externals, "lnt-compile-suite-src",
                           "project_list.json")) as f:
        data = json.load(f)

    for jobs in jobs_to_test:
        for project in data['projects']:
            # Check the style.
            yield ('build/%s' % (project['name'],),
                   curry(test_build, project=project, num_jobs=jobs))

def get_tests(test_suite_externals, flags_to_test, jobs_to_test):
    for item in get_single_file_tests(flags_to_test):
        yield item

    for item in get_full_build_tests(jobs_to_test, test_suite_externals):
        yield item

###

import builtintest
from optparse import OptionParser, OptionGroup

g_output_dir = None
usage_info = """
Script for testing compile time performance.

Currently this is only intended to test the raw compiler performance, not its
scalability or its performance in parallel builds.

This tests:
 - PCH Generation for Cocoa.h
   o File Size
   o Memory Usage
   o Time
 - Objective-C Compile Time, with PCH
   o File Sizes
   o Memory Usage
   o Time
 - C Compile Time, without PCH
   o File Sizes
   o Memory Usage
   o Time
 - Full Build Times
   o Total Build Time (serialized) (using xcodebuild)

TODO:
 - Objective-C Compile Time, with PCH
   o PCH Utilization

FIXME: One major hole here is that we aren't testing one situation which does
sometimes show up with PCH, where we have a PCH file + a second significant body
of code (e.g., a large user framework, or a poorly PCHified project). In
practice, this can be a significant hole because PCH has a substantial impact on
how lookup, for example, is done.

We run each of the tests above in a number of dimensions:
 - O0
 - O0 -g
 - Os

We run each of the compile time tests in various stages:
 - ### (driver time)
 - init (driver + compiler init)
 - fsyntax-only (lex/parse/sema time)
 - emit-llvm-only (IRgen time)
 - emit-llvm (.bc output time and size, mostly to track output file size)
 - S (codegen time and size)
 - c (assembly time and size)

FIXME: In the past, we have generated breakdown timings of full builds using
Make or xcodebuild by interposing scripts to stub out parts of the compilation
process. This is fragile, but can also be very useful when trying to understand
where the time is going in a full build.

FIXME: We may want to consider timing non-serial builds in order to start
measuring things like the full-system-performance impact on the compiler.
"""

class CompileTest(builtintest.BuiltinTest):
    def describe(self):
        return 'Single file compile-time performance testing'

    def run_test(self, name, args):
        global opts
        parser = OptionParser(
            ("%%prog %(name)s [options] [<output file>]\n" +
             usage_info) % locals())
        parser.add_option("-v", "--verbose", dest="verbose",
                          help="Show more test output",
                          action="store_true", default=False)
        parser.add_option("-s", "--sandbox", dest="sandbox_path",
                          help="Parent directory to build and run tests in",
                          type=str, default=None, metavar="PATH")

        group = OptionGroup(parser, "Test Options")
        group.add_option("", "--cc", dest="cc", type='str',
                         help="Compiler under test",
                         action="store", default=None)
        group.add_option("", "--test-externals", dest="test_suite_externals",
                         help="Path to the LLVM test-suite externals",
                         type=str, default=None, metavar="PATH")
        group.add_option("", "--machine-param", dest="machine_parameters",
                         metavar="NAME=VAL",
                         help="Add 'NAME' = 'VAL' to the machine parameters",
                         type=str, action="append", default=[])
        group.add_option("", "--run-param", dest="run_parameters",
                         metavar="NAME=VAL",
                         help="Add 'NAME' = 'VAL' to the run parameters",
                         type=str, action="append", default=[])
        group.add_option("", "--run-order", dest="run_order", metavar="STR",
                         help="String to use to identify and order this run",
                         action="store", type=str, default=None)
        parser.add_option_group(group)

        group = OptionGroup(parser, "Test Selection")
        group.add_option("", "--no-memory-profiling", dest="memory_profiling",
                         help="Disable memory profiling",
                         action="store_false", default=True)
        group.add_option("", "--multisample", dest="run_count", metavar="N",
                         help="Accumulate test data from multiple runs",
                         action="store", type=int, default=3)
        group.add_option("", "--show-tests", dest="show_tests",
                         help="Only list the availables tests that will be run",
                         action="store_true", default=False)
        group.add_option("", "--test", dest="tests", metavar="NAME",
                         help="Individual test to run",
                         action="append", default=[])
        group.add_option("", "--flags-to-test", dest="flags_to_test",
                         help="Add a set of flags to test (space separated)",
                         metavar="FLAGLIST", action="append", default=[])
        group.add_option("", "--jobs-to-test", dest="jobs_to_test",
                         help="Add a job count to test (full builds)",
                         metavar="NUM", action="append", default=[], type=int)
        parser.add_option_group(group)

        group = OptionGroup(parser, "Output Options")
        group.add_option("", "--no-machdep-info", dest="use_machdep_info",
                         help=("Don't put machine (instance) dependent "
                               "variables in machine info"),
                         action="store_false", default=True)
        group.add_option("", "--machine-name", dest="machine_name", type='str',
                         help="Machine name to use in submission [%default]",
                         action="store", default=platform.uname()[1])
        parser.add_option_group(group)

        opts,args = parser.parse_args(args)

        if len(args) != 0:
            parser.error("invalid number of arguments")

        # Validate options.
        if opts.cc is None:
            parser.error('--cc is required')
        if opts.sandbox_path is None:
            parser.error('--sandbox is required')
        if opts.test_suite_externals is None:
            parser.error("--test-externals option is required")

        # Set up the sandbox.
        global g_output_dir
        if not os.path.exists(opts.sandbox_path):
            print >>sys.stderr, "%s: creating sandbox: %r" % (
                timestamp(), opts.sandbox_path)
            os.mkdir(opts.sandbox_path)
        g_output_dir = os.path.join(os.path.abspath(opts.sandbox_path),
                                    "test-%s" % (
                timestamp().replace(' ','_').replace(':','-'),))
        try:
            os.mkdir(g_output_dir)
        except OSError,e:
            if e.errno == errno.EEXIST:
                parser.error("sandbox output directory %r already exists!" % (
                        g_output_dir,))
            else:
                raise

        # Collect machine and run information.
        machine_info, run_info = machineinfo.get_machine_information(
            opts.use_machdep_info)

        # FIXME: Include information on test source versions.
        #
        # FIXME: Get more machine information? Cocoa.h hash, for example.

        for name,cmd in (('sys_cc_version', ('/usr/bin/gcc','-v')),
                         ('sys_as_version', ('/usr/bin/as','-v','/dev/null')),
                         ('sys_ld_version', ('/usr/bin/ld','-v'))):
            run_info[name] = capture(cmd, include_stderr=True).strip()

        # Set command line machine and run information.
        for info,params in ((machine_info, opts.machine_parameters),
                            (run_info, opts.run_parameters)):
            for entry in params:
                if '=' not in entry:
                    name,value = entry,''
                else:
                    name,value = entry.split('=', 1)
                info[name] = value

        # Set user variables.
        variables = {}
        variables['cc'] = opts.cc
        variables['run_count'] = opts.run_count

        # Get compiler info.
        cc_info = lnt.testing.util.compilers.get_cc_info(variables['cc'])
        variables.update(cc_info)

        # Set the run order from the user, if given.
        if opts.run_order is not None:
            variables['run_order'] = opts.run_order
        else:
            # Otherwise, use the inferred run order.
            variables['run_order'] = cc_info['inferred_run_order']
            note("inferred run order to be: %r" % (variables['run_order'],))

        if opts.verbose:
            format = pprint.pformat(variables)
            msg = '\n\t'.join(['using variables:'] + format.splitlines())
            note(msg)

            format = pprint.pformat(machine_info)
            msg = '\n\t'.join(['using machine info:'] + format.splitlines())
            note(msg)

            format = pprint.pformat(run_info)
            msg = '\n\t'.join(['using run info:'] + format.splitlines())
            note(msg)

        # Compute the set of flags to test.
        if not opts.flags_to_test:
            flags_to_test = [('-O0',), ('-O0','-g',), ('-Os',)]
        else:
            flags_to_test = [string.split(' ')
                             for string in opts.flags_to_test]

        # Compute the set of job counts to use in full build tests.
        if not opts.jobs_to_test:
            jobs_to_test = [1, 2, 4, 8]
        else:
            jobs_to_test = opts.jobs_to_test

        # Compute the list of all tests.
        all_tests = get_tests(opts.test_suite_externals, flags_to_test,
                              jobs_to_test)

        # Show the tests, if requested.
        if opts.show_tests:
            print >>sys.stderr, 'Available Tests'
            for name in sorted(set(name for name,_ in all_tests)):
                print >>sys.stderr, '  %s' % (name,)
            print
            raise SystemExit

        # Find the tests to run.
        if not opts.tests:
            tests_to_run = list(all_tests)
        else:
            tests_to_run = []
            for name in opts.tests:
                matching_tests = [test
                                  for test in all_tests
                                  if name == test[0]]
                if not matching_tests:
                    parser.error(("invalid test name %r, use --show-tests to "
                                  "see available tests") % name)
                tests_to_run.extend(matching_tests)

        # Ensure output directory is available.
        if not os.path.exists(g_output_dir):
            os.mkdir(g_output_dir)

        # Create the test log.
        global test_log
        test_log_path = os.path.join(g_output_dir, 'test.log')
        test_log = open(test_log_path, 'w')

        # Tee the output to stderr as well.
        test_log = TeeStream(test_log, sys.stderr)

        # Execute the run.
        run_info.update(variables)
        run_info['tag'] = tag = 'compile'

        testsamples = []
        start_time = datetime.utcnow()
        print >>test_log, '%s: run started' % start_time.strftime(
            '%Y-%m-%d %H:%M:%S')
        try:
            for basename,test_fn in tests_to_run:
                for success,name,samples in test_fn(basename, run_info,
                                                         variables):
                    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    print >>test_log, '%s: collected sample: %r' % (
                        now, name)
                    print >>test_log, '%s:   %r' % (now, samples)
                    test_name = '%s.%s' % (tag, name)
                    if not success:
                        testsamples.append(lnt.testing.TestSamples(
                                test_name + '.status', [lnt.testing.FAIL]))
                    if samples:
                        testsamples.append(lnt.testing.TestSamples(
                                test_name, samples))
        except KeyboardInterrupt:
            raise SystemExit("\ninterrupted\n")
        except:
            import traceback
            print >>sys.stderr,'*** EXCEPTION DURING TEST, HALTING ***'
            print >>sys.stderr,'--'
            traceback.print_exc()
            print >>sys.stderr,'--'
            run_info['had_errors'] = 1
        end_time = datetime.utcnow()
        print >>test_log, '%s: run complete' % end_time.strftime(
            '%Y-%m-%d %H:%M:%S')

        test_log.close()

        # Package up the report.
        machine = lnt.testing.Machine(opts.machine_name, machine_info)
        run = lnt.testing.Run(start_time, end_time, info = run_info)

        return lnt.testing.Report(machine, run, testsamples)

def create_instance():
    return CompileTest()

__all__ = ['create_instance']
