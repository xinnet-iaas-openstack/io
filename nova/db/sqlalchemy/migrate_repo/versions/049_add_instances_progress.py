# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from sqlalchemy import *
from migrate import *

from nova import log as logging

meta = MetaData()

instances = Table('instances', meta,
    Column("id", Integer(), primary_key=True, nullable=False))

# Add progress column to instances table
progress = Column('progress', Integer())


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    try:
        instances.create_column(progress)
    except Exception:
        logging.error(_("progress column not added to instances table"))
        raise


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instances.drop_column(progress)
