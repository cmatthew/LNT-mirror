"""
Utility for submitting files to a web server over HTTP.
"""
import plistlib
import sys
import urllib
import urllib2
import contextlib
import json

import lnt.server.instance
from lnt.util import ImportData

# FIXME: I used to maintain this file in such a way that it could be used
# separate from LNT to do submission. This could be useful for adapting an
# older system to report to LNT, for example. It might be nice to factor the
# simplified submit code into a separate utility.


def _show_json_error(reply):
    try:
        error = json.loads(reply)
    except ValueError:
        print "error: {}".format(reply)
        return
    sys.stderr.write("error: lnt server: {}\n".format(error.get('error')))
    message = error.get('message', '')
    if message:
        sys.stderr.write(message + '\n')


def submitFileToServer(url, file, commit, updateMachine, mergeRun):
    with open(file, 'rb') as f:
        values = {
            'input_data': f.read(),
            'commit': "1" if commit else "0",
            'update_machine': "1" if updateMachine else "0",
            'merge': mergeRun,
        }
    headers = {'Accept': 'application/json'}
    data = urllib.urlencode(values)
    try:
        response = urllib2.urlopen(urllib2.Request(url, data, headers=headers))
    except urllib2.HTTPError as e:
        _show_json_error(e.read())
        return
    result_data = response.read()

    # The result is expected to be a JSON object.
    try:
        return json.loads(result_data)
    except:
        import traceback
        print "Unable to load result, not a valid JSON object."
        print
        print "Traceback:"
        traceback.print_exc()
        print
        print "Result:"
        print "error:", result_data
        return

    return reply


def submitFileToInstance(path, file, commit, updateMachine=False,
                         mergeRun='replace'):
    # Otherwise, assume it is a local url and submit to the default database
    # in the instance.
    instance = lnt.server.instance.Instance.frompath(path)
    config = instance.config
    db_name = 'default'
    with contextlib.closing(config.get_database(db_name)) as db:
        if db is None:
            raise ValueError("no default database in instance: %r" % (path,))
        return lnt.util.ImportData.import_and_report(
            config, db_name, db, file, format='<auto>', ts_name='nts',
            commit=commit, updateMachine=updateMachine, mergeRun=mergeRun)


def submitFile(url, file, commit, verbose, updateMachine=False,
               mergeRun='replace'):
    # If this is a real url, submit it using urllib.
    if '://' in url:
        result = submitFileToServer(url, file, commit, updateMachine, mergeRun)
    else:
        result = submitFileToInstance(url, file, commit, updateMachine,
                                      mergeRun)
    return result


def submitFiles(url, files, commit, verbose, updateMachine=False,
                mergeRun='replace'):
    results = []
    for file in files:
        result = submitFile(url, file, commit, verbose, updateMachine,
                            mergeRun)
        if result:
            results.append(result)
    return results
