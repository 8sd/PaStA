"""
PaStA - Patch Stack Analysis

Copyright (c) OTH Regensburg, 2016-2017

Author:
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>

This work is licensed under the terms of the GNU GPL, version 2.  See
the COPYING file in the top-level directory.
"""

from logging import getLogger

log = getLogger(__name__[-15:])


class Cluster:
    SEPARATOR = '=>'

    def __init__(self):
        self.classes = list()
        self.lookup = dict()
        self.tags = set()

    def optimize(self):
        # get optimized list by filtering orphaned elements
        self.classes = list(filter(None, self.classes))

        # reset lookup table
        self.lookup = dict()

        # recreate the lookup dictionary
        for i, keylist in enumerate(self.classes):
            for key in keylist:
                self.lookup[key] = i

    def ripup_cluster(self, representative):
        """
        Rips up a cluster. This removes all connections of the elements of the
        cluster and reinserts them as single-element clusters
        :return: Elements of the former cluster
        """
        id = self.lookup[representative]

        elems = self.classes.pop(id)
        for elem in elems:
            self.lookup.pop(elem)

        for elem in elems:
            self.insert_single(elem)

        return elems

    def remove_key(self, key):
        self.tags.discard(key)
        id = self.lookup.pop(key)
        self.classes[id].remove(key)

    def remove_single_element_clusters(self):
        single_element_clusters = set()
        for cluster in self:
            if len(cluster) == 1:
                single_element_clusters.add(list(cluster)[0])

        for representative in single_element_clusters:
            self.remove_key(representative)
        self.optimize()

        return len(single_element_clusters)

    def is_related(self, *elems):
        """
        Returns True, if _all_ elements are in the same equivalence class
        """
        ids = {self.lookup.get(x, None) for x in elems}

        if None in ids:
            return False

        return len(ids) == 1

    def is_unrelated(self, *elems):
        """
        Returns True, if _all_ elements are in their own class
        """
        num_elems = len(elems)
        ids = [self.lookup.get(x, None) for x in elems]
        num_elems -= ids.count(None)
        ids = set(ids)
        ids.discard(None)

        if len(ids) == num_elems:
            return True
        return False

    def insert_single(self, elem):
        if elem in self.lookup:
            return self.lookup[elem]

        self.classes.append(set([elem]))
        id = len(self.classes) - 1
        self.lookup[elem] = id

        return id

    def _merge_ids(self, *ids):
        new_class = set()
        new_id = min(ids)

        for id in ids:
            for elem in self.classes[id]:
                self.lookup[elem] = new_id
            new_class |= self.classes[id]
            self.classes[id] = set()

        self.classes[new_id] = new_class

        # truncate empty trailing list elements
        while not self.classes[-1]:
            self.classes.pop()

        return new_id

    def insert(self, *elems):
        if len(elems) == 0:
            return

        ids = [self.insert_single(elem) for elem in elems]

        # check if all elements are already in the same class
        if len(set(ids)) == 1:
            return ids[0]

        return self._merge_ids(*ids)

    def get_equivalence_id(self, key):
        return self.lookup[key]

    def tag(self, key, tag=True):
        if tag is True:
            self.tags.add(key)
        else:
            self.tags.discard(key)

    def has_tag(self, key):
        return key in self.tags

    def get_keys(self):
        return set(self.lookup.keys())

    def get_cluster(self, key):
        """
        Given a key, this function returns all elements of the cluster as a set
        """
        if key not in self:
            return None
        return self.classes[self.lookup[key]].copy()

    def get_tagged(self, key=None):
        """
        Returns all tagged entries that are related to key.

        If key is not specified, this function returns all tags.
        """
        if key:
            return self.tags.intersection(self.classes[self.lookup[key]])
        return self.tags

    def get_untagged(self, key=None):
        """
        Returns all untagged entries that are related to key.

        If key is not specified, this function returns all untagged.
        """
        if key:
            return self.classes[self.lookup[key]] - self.tags
        return set(self.lookup.keys()) - self.tags

    def __getitem__(self, item):
        if item in self.lookup:
            id = self.get_equivalence_id(item)
            return self.classes[id]

        return None

    def __len__(self):
        return len(self.classes)

    def __str__(self):
        retval = str()
        tagged_visited = set()

        untagged_list = [sorted(x) for x in self.iter_untagged()]
        untagged_list.sort()

        for untagged in untagged_list:
            tagged = self.get_tagged(untagged[0])
            tagged_visited |= tagged
            retval += ' '.join(sorted([str(x) for x in untagged]))
            if len(tagged):
                retval += ' ' + Cluster.SEPARATOR + ' ' + \
                          ' '.join(sorted([str(x) for x in tagged]))
            retval += '\n'

        # There may be clusters with upstream candidates only
        tagged = [x[1] for x in self.iter_tagged_only()]
        for cluster in tagged:
            if list(cluster)[0] in tagged_visited:
                continue

            cluster = ' '.join(sorted([str(x) for x in cluster]))
            retval += Cluster.SEPARATOR + ' ' + cluster + '\n'

        return retval

    def get_representative_system(self, compare_function):
        """
        Return a complete representative system of the equivalence class. Only
        untagged entries are considered.

        :param compare_function: a function that compares two elements of an
                                 equivalence class
        """
        retval = set()
        for equivclass in self.iter_untagged():
            equivclass = list(equivclass)
            if not equivclass:
                continue

            if len(equivclass) == 1:
                retval.add(equivclass[0])
                continue

            rep = equivclass[0]
            for element in equivclass[1:]:
                if compare_function(element, rep):
                    rep = element
            retval.add(rep)

        return retval

    def __iter__(self):
        # iterate over all classes, and return all items
        for elem in self.classes:
            if not elem:
                continue
            yield elem

    def iter_untagged(self):
        # iterate over all classes, but return untagged items only
        for elem in self.classes:
            untagged = elem - self.tags
            if not untagged:
                continue
            yield untagged

    def iter_tagged_only(self):
        # iterate only over classes that are tagged, and return both:
        # tagged and untagged
        for group in self: # calls self.__iter__()
            tagged = group & self.tags
            if len(tagged) == 0:
                continue
            untagged = group - tagged

            yield untagged, tagged

    def __contains__(self, item):
        return item in self.lookup

    def to_file(self, filename):
        self.optimize()
        with open(filename, 'w') as f:
            f.write(str(self))

    def get_key_of_element(self, elem):
        return self.lookup[elem]

    @staticmethod
    def from_file(filename, must_exist=False):
        def split_elements(elems):
            return list(filter(None, elems.split(' ')))

        retval = Cluster()

        try:
            with open(filename, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            log.warning('Equivalence class not found: %s' % filename)
            if must_exist:
                raise
            return retval

        if not (content and len(content)):
            return retval

        content = list(filter(None, content.splitlines()))
        for line in content:
            line = line.split(Cluster.SEPARATOR)
            # Append empty tagged list, if not present
            if len(line) == 1:
                line.append('')

            untagged, tagged = split_elements(line[0]), split_elements(line[1])

            retval.insert(*(untagged + tagged))
            for tag in tagged:
                retval.tag(tag)

        return retval
