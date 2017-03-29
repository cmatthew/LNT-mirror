"""
Base class for builtin-in tests.
"""

import sys
import os

from lnt.testing.util.misc import timestamp

import lnt.util.ServerUtil as ServerUtil
import lnt.util.ImportData as ImportData
import lnt.server.config as server_config
import lnt.server.db.v4db
import lnt.server.config


class BuiltinTest(object):
    def __init__(self):
        pass

    def describe(self):
        """"describe() -> str

        Return a short description of the test.
        """

    def run_test(self, name, args):
        """run_test(name, args) -> lnt.testing.Report

        Execute the test (accessed via name, for use in the usage message) with
        the given command line args.
        """
        raise RuntimeError("Abstract Method.")

    def log(self, message, ts=timestamp()):
        print >>sys.stderr, '%s: %s' % (ts, message)

    @staticmethod
    def print_report(report, output):
        """Print the report object to the output path."""
        if output == '-':
            output_stream = sys.stdout
        else:
            output_stream = open(output, 'w')
        print >> output_stream, report.render()
        if output_stream is not sys.stdout:
            output_stream.close()

    def submit(self, report_path, config, commit=True):
        """Submit the results file to the server.  If no server
        was specified, use a local mock server.

        report_path is the location of the json report file.  config
        holds options for submission url, and verbosity.  When commit
        is true, results will be saved in the server, otherwise you
        will just get back a report but server state is not altered.

        Returns the report from the server.
        """
        assert os.path.exists(report_path), "Failed report should have" \
            " never gotten here!"

        server_report = None
        if config.submit_url is not None:
            self.log("submitting result to %r" % (config.submit_url,))
            server_report = ServerUtil.submitFile(config.submit_url,
                                                  report_path,
                                                  commit,
                                                  config.verbose)
        else:
            # Simulate a submission to retrieve the results report.

            # Construct a temporary database and import the result.
            self.log("submitting result to dummy instance")

            db = lnt.server.db.v4db.V4DB("sqlite:///:memory:",
                                         server_config.Config.dummy_instance())
            server_report = ImportData.import_and_report(
                None, None, db, report_path, 'json', commit)

        assert server_report is not None, "Results were not submitted."

        ImportData.print_report_result(server_report, sys.stdout, sys.stderr,
                                       config.verbose)
        return server_report
