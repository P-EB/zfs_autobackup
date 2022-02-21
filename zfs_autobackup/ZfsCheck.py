from __future__ import print_function

import time
from signal import signal, SIGPIPE

from .TreeHasher import TreeHasher
from .BlockHasher import BlockHasher
from .ZfsNode import ZfsNode
from .util import *
from .CliBase import CliBase


class ZfsCheck(CliBase):

    def __init__(self, argv, print_arguments=True):

        # NOTE: common options and parameters are in ZfsAuto
        super(ZfsCheck, self).__init__(argv, print_arguments)

        self.node = ZfsNode(self.log, readonly=self.args.test, debug_output=self.args.debug_output)

    def get_parser(self):

        parser = super(ZfsCheck, self).get_parser()

        # positional arguments
        parser.add_argument('snapshot', metavar='SNAPSHOT', default=None, nargs='?', help='Snapshot to checksum')

        group = parser.add_argument_group('Hasher options')

        group.add_argument('--block-size', metavar="BYTES", default=4096, help="Read block-size, default %(default)s",
                           type=int)
        group.add_argument('--count', metavar="COUNT", default=int((100 * (1024 ** 2)) / 4096),
                           help="Hash chunks of COUNT blocks. Default %(default)s . (Chunk size is BYTES * COUNT) ", type=int)  # 100MiB

        group.add_argument('--check', '-c', metavar="FILE", default=None,
                           help="Read hashes from FILE and check them")

        return parser

    def parse_args(self, argv):
        args = super(ZfsCheck, self).parse_args(argv)

        if args.test:
            self.warning("TEST MODE - NOT DOING ANYTHING USEFULL")
            self.log.show_debug = True  # show at least what we would do

        if args.snapshot is None:
            self.error("Please specify SNAPSHOT")
            sys.exit(1)

        return args

    def hash_filesystem(self, snapshot, count, bs):
        """ recursively hash all files in this snapshot, using block_hash_tree()

        :type snapshot: ZfsDataset.ZfsDataset
        """
        mnt = "/tmp/" + tmp_name()

        try:
            self.debug("Create temporary mount point {}".format(mnt))
            self.node.run(["mkdir", mnt])

            snapshot.mount(mnt)

            tree_hasher=TreeHasher(BlockHasher(count=count, bs=bs))

            self.debug("Hashing tree: {}".format(mnt))
            if not self.args.test:

                # generator=tree_hasher.generate(mnt)
                # tree_hasher.compare(mnt, generator)


                for (file, block, hash) in tree_hasher.generate(mnt):
                    print("{}\t{}\t{}".format(file, block, hash))
                    sys.stdout.flush() #important, to generate SIGPIPES on ssh disconnect


        finally:
            snapshot.unmount()
            self.debug("Cleaning up temporary mount point")
            self.node.run(["rmdir", mnt], hide_errors=True, valid_exitcodes=[])

    # NOTE: https://www.google.com/search?q=Mount+Path+Limit+freebsd
    # Freebsd has limitations regarding path length, so we have to clone it so the part stays sort
    def activate_volume_snapshot(self, snapshot):
        """clone volume, waits and tries to findout /dev path to the volume, in a compatible way. (linux/freebsd/smartos)"""

        clone_name = get_tmp_clone_name(snapshot)
        clone = snapshot.clone(clone_name)

        # TODO: add smartos location to this list as well
        locations = [
            "/dev/zvol/" + clone_name
        ]

        clone.debug("Waiting for /dev entry to appear in: {}".format(locations))
        time.sleep(0.1)

        start_time = time.time()
        while time.time() - start_time < 10:
            for location in locations:
                if os.path.exists(location):
                    return location

                # fake it in testmode
                if self.args.test:
                    return location

            time.sleep(1)

        raise (Exception("Timeout while waiting for /dev entry to appear. (looking in: {})".format(locations)))

    def deacitvate_volume_snapshot(self, snapshot):
        """destroys temporary volume snapshot"""
        clone_name = get_tmp_clone_name(snapshot)
        clone = snapshot.zfs_node.get_dataset(clone_name)
        clone.destroy(deferred=True, verbose=False)

    def hash_volume(self, snapshot, count, bs):
        try:
            dev=self.activate_volume_snapshot(snapshot)
            block_hasher=BlockHasher(count=count, bs=bs)

            self.debug("Hashing dev: {}".format(dev))
            if not self.args.test:
                for (block, hash) in block_hasher.generate(dev):
                    print("{}\t{}".format(block, hash))
                    sys.stdout.flush() #important, to generate SIGPIPES on ssh disconnect

        finally:
            self.deacitvate_volume_snapshot(snapshot)

    def run(self):

        snapshot = self.node.get_dataset(self.args.snapshot)

        if not snapshot.exists:
            snapshot.error("Snapshot not found")
            sys.exit(1)

        if not snapshot.is_snapshot:
            snapshot.error("Dataset should be a snapshot")
            sys.exit(1)

        dataset_type = snapshot.parent.properties['type']

        snapshot.verbose("Generating checksums...")

        if dataset_type == 'volume':
            self.hash_volume(snapshot, self.args.count, self.args.block_size)
        elif dataset_type == 'filesystem':
            self.hash_filesystem(snapshot, self.args.count, self.args.block_size)
        else:
            raise Exception("huh?")


def cli():
    import sys
    signal(SIGPIPE, sigpipe_handler)

    sys.exit(ZfsCheck(sys.argv[1:], False).run())

    # block_hasher=BlockHasher()

    # if sys.argv[1]=="s":
    #     for ( fname, nr, hash ) in TreeHasher(block_hasher).generate("/usr/src/linux-headers-5.14.14-051414"):
    #         print("{}\t{}\t{}".format(fname, nr, hash))
    #
    # if sys.argv[1]=="r":
    #
    #     def gen():
    #         for line in sys.stdin:
    #             ( fname, nr, hash)=line.rstrip().split('\t')
    #             yield (fname, int(nr), hash)
    #
    #     TreeHasher(block_hasher).compare("/usr/src/linux-headers-5.14.14-051414", gen())


if __name__ == "__main__":

    cli()