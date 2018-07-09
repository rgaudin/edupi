#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4 nu

import io
import os
import shutil
import zipfile
import logging

import magic
from django.core import files
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.core.management.base import BaseCommand, CommandError

from cntapp.helpers import get_root_dirs_query
from cntapp.models import Directory, Document
from cntapp.serializers import DocumentSerializer


logger = logging.getLogger(__name__)
mime = magic.Magic(mime=True)


class TempUploadedFile(UploadedFile):

    def __init__(self, fpath):
        self._tmp_fpath = fpath
        with open(fpath, 'rb') as fp:
            f = files.File(fp)
            content = f.read()
            super(TempUploadedFile, self).__init__(
                file=io.BytesIO(content),
                name=os.path.basename(fpath),
                content_type=mime.from_file(fpath),
                size=len(content),
                charset=None,
                content_type_extra=None)
    def temporary_file_path(self):
        return self._tmp_fpath


def splitall(fpath):
    ''' splits folders from a path (from path.py) '''
    parts = []
    loc = fpath
    while loc != os.curdir and loc != os.pardir:
        prev = loc
        loc, child = os.path.split(prev)
        if loc == prev:
            break
        parts.append(child)
    parts.append(loc)
    parts.reverse()
    return parts


def create_dir(name):
    d = Directory(name=name)
    d.save()
    return d


def get_or_create_root_dir(name):
    try:
        root_directory = get_root_dirs_query().get(name=name)
        return root_directory, False
    except Directory.DoesNotExist:
        root_directory = create_dir(name)
        return root_directory, True


def check_file_names(fname):
    ''' exclude files based on their names '''
    if fname in ('.DS_Store',):
        return False
    return True


def get_dir_by_path(source_path, tree_root):
    root_levels = len(splitall(tree_root))

    # file path to source folder
    source_folder = os.path.split(source_path)[0]

    # list of directories to the source folder
    relative_paths = splitall(source_folder)[root_levels:]
    root_dir, created = get_or_create_root_dir(relative_paths[0])

    current_dir = root_dir

    for dir_name in relative_paths[1:]:
        sub_dir_names = [d.name for d in current_dir.get_sub_dirs()]
        if dir_name not in sub_dir_names:
            return None
        else:
            current_dir = current_dir.get_sub_dirs().get(name=dir_name)

    return current_dir


def create_document(fpath):
    fname = os.path.basename(fpath)
    validated_data = {
        'file': TempUploadedFile(fpath),
        'name': fname,
    }
    return DocumentSerializer().create(validated_data)


class Command(BaseCommand):
    help = 'Import documents into EduPi from a document tree'

    def add_arguments(self, parser):
        parser.add_argument("tree", help="The path of the tree root")

    def handle(self, *args, **options):

        tree_root = os.path.abspath(options['tree'])
        if not os.path.exists(tree_root):
            raise CommandError("Document tree root is not reachable: `{}`"
                               .format(tree_root))

        nb_added_documents = 0

        # handle files on root: edupi wants files in folders
        # if files are on root, lets move them to a subfolder
        root_files = [fname for fname in filter(check_file_names,
                                                os.listdir(tree_root))
                      if os.path.isfile(os.path.join(tree_root, fname))]
        if len(root_files):
            default_folder_name = "Documents"
            logger.info("Moving {} root-files into the {} sub folder"
                        .format(len(root_files), default_folder_name))

            default_folder = os.path.join(tree_root, default_folder_name)
            os.makedirs(default_folder, exist_ok=True)
            for fname in root_files:
                shutil.move(os.path.join(tree_root, fname),
                            os.path.join(default_folder, fname))

        root_levels = len(splitall(tree_root))
        for root, dirs, files in os.walk(tree_root):
            for folder_name in dirs:
                # full path to source folder
                source_path = os.path.join(root, folder_name)

                # list of directories to get/create
                relative_paths = splitall(source_path)[root_levels:]

                # root folder is special in EduPi
                root_name = relative_paths[0]
                # get or retrieve root path
                root_directory, created = get_or_create_root_dir(root_name)
                if created:
                    logger.info("retrieved existing root directory `{}`"
                                .format(root_directory))
                else:
                    logger.info("retrieved root directory `{}`"
                                .format(root_directory))

                # get or create all sub dirs underneath
                current_dir = root_directory
                for dir_name in relative_paths[1:]:
                    if dir_name not in [d.name for d
                                        in current_dir.get_sub_dirs()]:
                        sub_directory = create_dir(dir_name)
                        current_dir.add_sub_dir(sub_directory)
                        current_dir = sub_directory
                        logger.info("created sub_directory `{}`".format(
                            "/".join([d.name for d
                                      in current_dir.get_paths()[0]])))
                    else:
                        current_dir = current_dir.get_sub_dirs().get(
                            name=dir_name)
                        logger.info("retrieved sub_directory `{}`".format(
                            "/".join([d.name for d
                                      in current_dir.get_paths()[0]])))

            for fname in filter(check_file_names, files):
                # full path to source file
                source_path = os.path.join(root, fname)
                # file path to source folder
                source_folder = os.path.split(source_path)[0]
                # list of directories to the source folder
                relative_paths = splitall(source_folder)[root_levels:]

                logger.info("Creating Document for {} -- {}"
                            .format(relative_paths, fname))
                # retrieve the mathcing Directory
                file_directory = get_dir_by_path(source_path, tree_root)
                assert file_directory is not None
                # create the floating Document
                document = create_document(source_path)
                # attach Document to Directory
                file_directory.documents.add(document)
                # update counter
                nb_added_documents += 1

        self.stdout.write("Done. Added {} documents from {}"
                          .format(nb_added_documents, tree_root))
