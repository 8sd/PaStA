"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import os
import sys
from pypasta import *

def ignored_patches(config, prog, argv):
    parser = argparse.ArgumentParser(prog=prog,
                                      description='Check consistency of mailbox '
                                                  'result')

    args = parser.parse_args(argv)

    if config.mode != config.Mode.MBOX:
        log.error('Only works in Mbox mode!')
        return -1

    found = list()
    patches = list()

    # Load patches
    ## load inbox
    mbox = Mbox(config)

    ##extract patches 
    print(len(mbox.message_ids()))
    for message_id in mbox.message_ids(): # This can be parallized
        try:
            patches.append(mbox.__getitem__(message_id))
        except:
            continue
    print (len(patches))

    # Iterate patches
    for patches in patches:
        # check if patch has mail
            # → ignore
        # check if patch is merged
            # → ignore
        # → patch was ignored
        found.append(patches)
    # Write to file
    #print(found)
