#!/usr/bin/python
#  -*- Python -*-

"""Complicated notification for CVS checkins.

This script is used to provide email notifications of changes to the CVS
repository.  These email changes will include context diffs of the changes.
Really big diffs will be trimmed.

This script is run from a CVS loginfo file (see $CVSROOT/CVSROOT/loginfo).  To
set this up, create a loginfo entry that looks something like this:

    mymodule /path/to/this/script %%s some-email-addr@your.domain

In this example, whenever a checkin that matches `mymodule' is made, this
script is invoked, which will generate the diff containing email, and send it
to some-email-addr@your.domain.

    Note: This module used to also do repository synchronizations via
    rsync-over-ssh, but since the repository has been moved to SourceForge,
    this is no longer necessary.  The syncing functionality has been ripped
    out in the 3.0, which simplifies it considerably.  Access the 2.x versions
    to refer to this functionality.  Because of this, the script is misnamed.

It no longer makes sense to run this script from the command line.  Doing so
will only print out this usage information.

Usage:

    %(PROGRAM)s [options] <%%S> email-addr [email-addr ...]

Where options is:

    --cvsroot=<path>
    	Use <path> as the environment variable CVSROOT.  Otherwise this
    	variable must exist in the environment.

    --help
    -h
        Print this text.

    --context=#
    -C #
        Include # lines of context around lines that differ (default: 2).

    -c
        Produce a context diff (default).

    -u
        Produce a unified diff (smaller, but harder to read).

    --head
        Only report commits to the CVS HEAD

    <%%S>
        CVS %%s loginfo expansion.  When invoked by CVS, this will be a single
        string containing the directory the checkin is being made in, relative
        to $CVSROOT, followed by the list of files that are changing.  If the
        %%s in the loginfo file is %%{sVv}, context diffs for each of the
        modified files are included in any email messages that are generated.

    email-addrs
        At least one email address.

"""
# hack to get around the fact that it is installed in my home dir
import os
import sys
import string
import time
import getopt
import re

# Diff trimming stuff
DIFF_HEAD_LINES = 20
DIFF_TAIL_LINES = 20
DIFF_TRUNCATE_IF_LARGER = 1000

PROGRAM = sys.argv[0]

# Notification arguments to mail
MAILARGS = ' -s "CVS: %(SUBJECT)s" %(PEOPLE)s 2>&1 > /dev/null'



def fileExists(f):
    try:
        file = open(f)
    except IOError:
        exists = 0
    else:
        exists = 1
    return exists



def usage(code, msg=''):
    print __doc__ % globals()
    if msg:
        print msg
    sys.exit(code)



def calculate_diff(filespec, contextlines):
    if fileExists("/usr/bin/cvs"):
        CVS = "/usr/bin/cvs"
    elif fileExists("/usr/local/bin/cvs"):
        CVS = "/usr/local/bin/cvs"
    elif fileExists("/bin/cvs"):
        CVS = "/bin/cvs"
    else:
        CVS = "cvs"

    try:
        file, oldrev, newrev = string.split(filespec, ',')
    except ValueError:
        # No diff to report
        return '***** Bogus filespec: %s' % filespec
    if oldrev == 'NONE':
        try:
            if os.path.exists(file):
                fp = open(file)
            else:
                update_cmd = '%s -fn update -r %s -p %s' % (CVS, newrev, file)
                fp = os.popen(update_cmd)
            lines = fp.readlines()
            fp.close()
            lines.insert(0, '--- NEW FILE: %s ---\n' % file)
        except IOError, e:
            lines = ['***** Error reading new file: ',
                     str(e), '\n***** file: ', file, ' cwd: ', os.getcwd()]
    elif newrev == 'NONE':
        lines = ['--- %s DELETED ---\n' % file]
    else:
        # This /has/ to happen in the background, otherwise we'll run into CVS
        # lock contention.  What a crock.
        if contextlines > 0:
            difftype = "-C " + str(contextlines)
        else:
            difftype = "-u"
        diffcmd = '%s -f diff -w -kk %s -r %s -r %s %s' % (
            CVS, difftype, oldrev, newrev, file)
        fp = os.popen(diffcmd)
        lines = fp.readlines()
        sts = fp.close()
        # ignore the error code, it always seems to be 1 :(
##        if sts:
##            return 'Error code %d occurred during diff\n' % (sts >> 8)
    if len(lines) > DIFF_TRUNCATE_IF_LARGER:
        removedlines = len(lines) - DIFF_HEAD_LINES - DIFF_TAIL_LINES
        del lines[DIFF_HEAD_LINES:-DIFF_TAIL_LINES]
        lines.insert(DIFF_HEAD_LINES,
                     '[...%d lines suppressed...]\n' % removedlines)
    return string.join(lines, '')



def blast_mail(mailcmd, filestodiff, contextlines):
    # cannot wait for child process or that will cause parent to retain cvs
    # lock for too long.  Urg!
    if not os.fork():
        # in the child
        # give up the lock you cvs thang!
        time.sleep(2)
        fp = os.popen(mailcmd, 'w')
        fp.write(sys.stdin.read())
        fp.write('\n')
        # append the diffs if available
        for file in filestodiff:
            fp.write(calculate_diff(file, contextlines))
            fp.write('\n')
        fp.close()
        # doesn't matter what code we return, it isn't waited on
        os._exit(0)



# scan args for options
def main():
    headonly = 0
    contextlines = 2
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hC:cu', ['context=', 'cvsroot=', 'help', 'head'])
    except getopt.error, msg:
        usage(1, msg)

    # parse the options
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            usage(0)
	elif opt == '--head':
	    headonly = 1
        elif opt == '--cvsroot':
            os.environ['CVSROOT'] = arg
        elif opt in ('-C', '--context'):
            contextlines = int(arg)
        elif opt == '-c':
            if contextlines <= 0:
                contextlines = 2
        elif opt == '-u':
            contextlines = 0

    # What follows is the specification containing the files that were
    # modified.  The argument actually must be split, with the first component
    # containing the directory the checkin is being made in, relative to
    # $CVSROOT, followed by the list of files that are changing.
    if not args:
        usage(1, 'No CVS module specified')
    SUBJECT = args[0]
    specs = string.split(args[0])
    del args[0]

    if headonly:
	# determine if this is a commit to head or to a branch by counting
	# the number of dots in the version number.
	dotRegexp = r'[\.]'
	commaRegexp = r'[,]'
	commaCount = re.compile(commaRegexp, re.S).findall(SUBJECT)
	dotCount = re.compile(dotRegexp, re.S).findall(SUBJECT)
	if dotCount != commaCount:
	    sys.exit(0)

    # The remaining args should be the email addresses
    if not args:
        usage(1, 'No recipients specified')

    # Now do the mail command
    PEOPLE = string.join(args)
    if fileExists("/bin/mail"):
        MAIL = "/bin/mail"
    elif fileExists("/usr/bin/mail"):
        MAIL = "/usr/bin/mail"
    elif fileExists("/usr/local/bin/mail"):
        MAIL = "/usr/local/bin/mail"
    else:
        MAIL = "mail"
    mailcmd = MAIL + MAILARGS % vars()

    print 'Mailing %s...' % PEOPLE
    if specs == ['-', 'Imported', 'sources']:
        return
    if specs[-3:] == ['-', 'New', 'directory']:
        del specs[-3:]
    print 'Generating notification message...'
    blast_mail(mailcmd, specs[1:], contextlines)
    print 'Generating notification message... done.'



if __name__ == '__main__':
    main()
    sys.exit(0)