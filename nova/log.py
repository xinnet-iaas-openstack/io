# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Nova logging handler.

This module adds to logging functionality by adding the option to specify
a context object when calling the various log methods.  If the context object
is not specified, default formatting is used. Additionally, an instance uuid
may be passed as part of the log message, which is intended to make it easier
for admins to find messages related to a specific instance.

It also allows setting of formatting information through flags.

"""

import cStringIO
import inspect
import json
import logging
import logging.handlers
import os
import stat
import sys
import traceback

import nova
from nova import flags
from nova import local
from nova.openstack.common import cfg
from nova import version


log_opts = [
    cfg.StrOpt('logging_context_format_string',
               default='%(asctime)s %(levelname)s %(name)s [%(request_id)s '
                       '%(user_id)s %(project_id)s] %(instance)s'
                       '%(message)s',
               help='format string to use for log messages with context'),
    cfg.StrOpt('logging_default_format_string',
               default='%(asctime)s %(levelname)s %(name)s [-] %(instance)s'
                       '%(message)s',
               help='format string to use for log messages without context'),
    cfg.StrOpt('logging_debug_format_suffix',
               default='from (pid=%(process)d) %(funcName)s '
                       '%(pathname)s:%(lineno)d',
               help='data to append to log format when level is DEBUG'),
    cfg.StrOpt('logging_exception_prefix',
               default='(%(name)s): TRACE: ',
               help='prefix each line of exception output with this format'),
    cfg.StrOpt('instance_format',
               default='[instance: %(uuid)s] ',
               help='If an instance is passed with the log message, format '
                    'it like this'),
    cfg.ListOpt('default_log_levels',
                default=[
                  'amqplib=WARN',
                  'sqlalchemy=WARN',
                  'boto=WARN',
                  'suds=INFO',
                  'eventlet.wsgi.server=WARN'
                  ],
                help='list of logger=LEVEL pairs'),
    cfg.BoolOpt('use_syslog',
                default=False,
                help='output to syslog'),
    cfg.BoolOpt('publish_errors',
                default=False,
                help='publish error events'),
    cfg.StrOpt('logfile',
               default=None,
               help='output to named file'),
    cfg.BoolOpt('use_stderr',
                default=True,
                help='log to standard error'),
    ]

FLAGS = flags.FLAGS
FLAGS.add_options(log_opts)

# A list of things we want to replicate from logging.
# levels
CRITICAL = logging.CRITICAL
FATAL = logging.FATAL
ERROR = logging.ERROR
WARNING = logging.WARNING
WARN = logging.WARN
INFO = logging.INFO
DEBUG = logging.DEBUG
NOTSET = logging.NOTSET


# methods
getLogger = logging.getLogger
debug = logging.debug
info = logging.info
warning = logging.warning
warn = logging.warn
error = logging.error
exception = logging.exception
critical = logging.critical
log = logging.log


# handlers
StreamHandler = logging.StreamHandler
WatchedFileHandler = logging.handlers.WatchedFileHandler
# logging.SysLogHandler is nicer than logging.logging.handler.SysLogHandler.
SysLogHandler = logging.handlers.SysLogHandler


# our new audit level
AUDIT = logging.INFO + 1
logging.addLevelName(AUDIT, 'AUDIT')


def _dictify_context(context):
    if context is None:
        return None
    if not isinstance(context, dict) \
    and getattr(context, 'to_dict', None):
        context = context.to_dict()
    return context


def _get_binary_name():
    return os.path.basename(inspect.stack()[-1][1])


def _get_log_file_path(binary=None):
    if FLAGS.logfile:
        return FLAGS.logfile
    if FLAGS.logdir:
        binary = binary or _get_binary_name()
        return '%s.log' % (os.path.join(FLAGS.logdir, binary),)


class NovaLogger(logging.Logger):
    """NovaLogger manages request context and formatting.

    This becomes the class that is instantiated by logging.getLogger.

    """

    def __init__(self, name, level=NOTSET):
        logging.Logger.__init__(self, name, level)
        self.setup_from_flags()

    def setup_from_flags(self):
        """Setup logger from flags."""
        level = NOTSET
        for pair in FLAGS.default_log_levels:
            logger, _sep, level_name = pair.partition('=')
            # NOTE(todd): if we set a.b, we want a.b.c to have the same level
            #             (but not a.bc, so we check the dot)
            if self.name == logger or self.name.startswith("%s." % logger):
                level = globals()[level_name]
        self.setLevel(level)

    def _update_extra(self, params):
        if 'extra' not in params:
            params['extra'] = {}
        extra = params['extra']

        context = None
        if 'context' in params:
            context = params['context']
            del params['context']
        if not context:
            context = getattr(local.store, 'context', None)
        if context:
            extra.update(_dictify_context(context))

        if 'instance' in params:
            extra.update({'instance': (FLAGS.instance_format
                                       % params['instance'])})
            del params['instance']
        else:
            extra.update({'instance': ''})

        extra.update({"nova_version": version.version_string_with_vcs()})

    #NOTE(ameade): The following calls to _log must be maintained as direct
    #calls. _log introspects the call stack to get information such as the
    #filename and line number the logging method was called from.

    def log(self, lvl, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(lvl):
            self._log(lvl, msg, args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(DEBUG):
            self._log(DEBUG, msg, args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(INFO):
            self._log(INFO, msg, args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(WARN):
            self._log(WARN, msg, args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(WARNING):
            self._log(WARNING, msg, args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(ERROR):
            self._log(ERROR, msg, args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(CRITICAL):
            self._log(CRITICAL, msg, args, **kwargs)

    def fatal(self, msg, *args, **kwargs):
        self._update_extra(kwargs)
        if self.isEnabledFor(FATAL):
            self._log(FATAL, msg, args, **kwargs)

    def audit(self, msg, *args, **kwargs):
        """Shortcut for our AUDIT level."""
        self._update_extra(kwargs)
        if self.isEnabledFor(AUDIT):
            self._log(AUDIT, msg, args, **kwargs)

    def addHandler(self, handler):
        """Each handler gets our custom formatter."""
        handler.setFormatter(_formatter)
        return logging.Logger.addHandler(self, handler)

    def exception(self, msg, *args, **kwargs):
        """Logging.exception doesn't handle kwargs, so breaks context."""
        if not kwargs.get('exc_info'):
            kwargs['exc_info'] = 1
        self.error(msg, *args, **kwargs)
        # NOTE(todd): does this really go here, or in _log ?
        extra = kwargs.get('extra')
        if not extra:
            return
        env = extra.get('environment')
        if env:
            env = env.copy()
            for k in env.keys():
                if not isinstance(env[k], str):
                    env.pop(k)
            message = 'Environment: %s' % json.dumps(env)
            kwargs.pop('exc_info')
            self.error(message, **kwargs)


class NovaFormatter(logging.Formatter):
    """A nova.context.RequestContext aware formatter configured through flags.

    The flags used to set format strings are: logging_context_format_string
    and logging_default_format_string.  You can also specify
    logging_debug_format_suffix to append extra formatting if the log level is
    debug.

    For information about what variables are available for the formatter see:
    http://docs.python.org/library/logging.html#formatter

    """

    def format(self, record):
        """Uses contextstring if request_id is set, otherwise default."""
        if record.__dict__.get('request_id', None):
            self._fmt = FLAGS.logging_context_format_string
        else:
            self._fmt = FLAGS.logging_default_format_string

        if record.levelno == logging.DEBUG \
        and FLAGS.logging_debug_format_suffix:
            self._fmt += " " + FLAGS.logging_debug_format_suffix

        # Cache this on the record, Logger will respect our formated copy
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info, record)
        return logging.Formatter.format(self, record)

    def formatException(self, exc_info, record=None):
        """Format exception output with FLAGS.logging_exception_prefix."""
        if not record:
            return logging.Formatter.formatException(self, exc_info)
        stringbuffer = cStringIO.StringIO()
        traceback.print_exception(exc_info[0], exc_info[1], exc_info[2],
                                  None, stringbuffer)
        lines = stringbuffer.getvalue().split('\n')
        stringbuffer.close()
        formatted_lines = []
        for line in lines:
            pl = FLAGS.logging_exception_prefix % record.__dict__
            fl = '%s%s' % (pl, line)
            formatted_lines.append(fl)
        return '\n'.join(formatted_lines)


_formatter = NovaFormatter()


class NovaRootLogger(NovaLogger):
    def __init__(self, name, level=NOTSET):
        self.logpath = None
        self.filelog = None
        self.streamlog = None
        self.syslog = None
        NovaLogger.__init__(self, name, level)

    def setup_from_flags(self):
        """Setup logger from flags."""
        global _filelog
        if self.syslog:
            self.removeHandler(self.syslog)
            self.syslog = None
        if FLAGS.use_syslog:
            self.syslog = SysLogHandler(address='/dev/log')
            self.addHandler(self.syslog)
        logpath = _get_log_file_path()
        if logpath:
            if logpath != self.logpath:
                self.removeHandler(self.filelog)
                self.filelog = WatchedFileHandler(logpath)
                self.addHandler(self.filelog)
                self.logpath = logpath

                mode = int(FLAGS.logfile_mode, 8)
                st = os.stat(self.logpath)
                if st.st_mode != (stat.S_IFREG | mode):
                    os.chmod(self.logpath, mode)
        else:
            self.removeHandler(self.filelog)
        if self.streamlog:
            self.removeHandler(self.streamlog)
            self.streamlog = None
        if FLAGS.use_stderr:
            self.streamlog = StreamHandler()
            self.addHandler(self.streamlog)
        if FLAGS.publish_errors:
            self.addHandler(PublishErrorsHandler(ERROR))
        if FLAGS.verbose:
            self.setLevel(DEBUG)
        else:
            self.setLevel(INFO)


class PublishErrorsHandler(logging.Handler):
    def emit(self, record):
        nova.notifier.api.notify('nova.error.publisher', 'error_notification',
            nova.notifier.api.ERROR, dict(error=record.msg))


def handle_exception(type, value, tb):
    extra = {}
    if FLAGS.verbose:
        extra['exc_info'] = (type, value, tb)
    logging.root.critical(str(value), **extra)


def reset():
    """Resets logging handlers.  Should be called if FLAGS changes."""
    for logger in NovaLogger.manager.loggerDict.itervalues():
        if isinstance(logger, NovaLogger):
            logger.setup_from_flags()


def setup():
    """Setup nova logging."""
    if not isinstance(logging.root, NovaRootLogger):
        logging._acquireLock()
        for handler in logging.root.handlers:
            logging.root.removeHandler(handler)
        logging.root = NovaRootLogger("nova")
        NovaLogger.root = logging.root
        NovaLogger.manager.root = logging.root
        for logger in NovaLogger.manager.loggerDict.itervalues():
            logger.root = logging.root
            if isinstance(logger, logging.Logger):
                NovaLogger.manager._fixupParents(logger)
        NovaLogger.manager.loggerDict["nova"] = logging.root
        logging._releaseLock()
        sys.excepthook = handle_exception
        reset()


root = logging.root
logging.setLoggerClass(NovaLogger)


def audit(msg, *args, **kwargs):
    """Shortcut for logging to root log with severity 'AUDIT'."""
    logging.root.audit(msg, *args, **kwargs)


class WritableLogger(object):
    """A thin wrapper that responds to `write` and logs."""

    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level

    def write(self, msg):
        self.logger.log(self.level, msg)
