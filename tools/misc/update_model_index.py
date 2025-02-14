#!/usr/bin/env python

# This tool is used to update model-index.yml which is required by MIM, and
# will be automatically called as a pre-commit hook. The updating will be
# triggered if any change of model information (.md files in configs/) has been
# detected before a commit.

import glob
import os.path as osp
import re
import sys

import mmcv

MMPOSE_ROOT = osp.dirname(osp.dirname(osp.dirname(__file__)))


def dump_yaml_and_check_difference(obj, file):
    """Dump object to a yaml file, and check if the file content is different
    from the original.

    Args:
        obj (any): The python object to be dumped.
        file (str): YAML filename to dump the object to.
    Returns:
        Bool: If the target YAML file is different from the original.
    """

    original = None
    if osp.isfile(file):
        with open(file, 'r', encoding='utf-8') as f:
            original = f.read()

    with open(file, 'w', encoding='utf-8') as f:
        mmcv.dump(obj, f, file_format='yaml', sort_keys=False)

    is_different = True
    if original is not None:
        with open(file, 'r') as f:
            new = f.read()
        is_different = (original != new)

    return is_different


def collate_metrics(keys):
    """Collect metrics from the first row of the table.

    Args:
        keys (List): Elements in the first row of the table.

    Returns:
        List: A list of metrics.
    """
    all_metrics = [
        'acc', 'ap', 'ar', 'pck', 'auc', '3dpck', 'p-3dpck', '3dauc',
        'p-3dauc', 'epe', 'nme', 'mpjpe', 'p-mpjpe', 'n-mpjpe', 'mean', 'head',
        'sho', 'elb', 'wri', 'hip', 'knee', 'ank', 'total'
    ]
    used_metrics = []
    metric_idx = []
    for idx, key in enumerate(keys):
        if key in ['Arch', 'Input Size', 'ckpt', 'log']:
            continue
        for metric in all_metrics:
            if metric.upper() in key or metric.capitalize() in key:
                used_metric = ''
                i = 0
                while i < len(key):
                    # skip ``<...>``
                    if key[i] == '<':
                        while key[i] != '>':
                            i += 1
                    # omit bold or italic
                    elif key[i] == '*' or key[i] == '_':
                        used_metric += ' '
                    else:
                        used_metric += key[i]
                    i += 1
                re.sub(' +', ' ', used_metric)
                used_metric = used_metric.strip()
                if metric in ['ap', 'ar']:
                    match = re.search(r'\d+', used_metric)
                    if match is not None:
                        l, r = match.span(0)
                        digits = match.group(0)
                        used_metric = used_metric[:l] + '@' + \
                            str(int(digits) * 0.01) + used_metric[r:]
                used_metrics.append(used_metric)
                metric_idx.append(idx)
                break
    return used_metrics, metric_idx


def get_task_name(md_file):
    """Get task name from README.md".

    Args:
        md_file: Path to .md file.

    Returns:
        Str: Task name.
    """
    task_dir = osp.relpath(md_file, MMPOSE_ROOT).rsplit(osp.sep, 3)[0]
    readme_file = osp.join(task_dir, 'README.md')
    with open(readme_file, 'r', encoding='utf-8') as f:
        task = f.readline()[2:].strip()
    return task


def parse_md(md_file):
    """Parse .md file and convert it to a .yml file which can be used for MIM.

    Args:
        md_file: Path to .md file.
    Returns:
        Bool: If the target YAML file is different from the original.
    """
    collection_name = osp.splitext(osp.basename(md_file))[0]
    collection = dict(
        Name=collection_name,
        Metadata={'Architecture': []},
        README=osp.relpath(md_file, MMPOSE_ROOT),
        Paper=[])
    models = []
    task = get_task_name(md_file)
    with open(md_file, 'r') as md:
        lines = md.readlines()
        i = 0
        while i < len(lines):
            # parse reference
            if lines[i][:2] == '<!':
                url, name = re.findall(r'<a href="(.*)">(.*)</a>',
                                       lines[i + 3])[0]
                name = name.split('(', 1)[0].strip()
                # get architecture
                if 'ALGORITHM' in lines[i] or 'BACKBONE' in lines[i]:
                    collection['Metadata']['Architecture'].append(name)
                # get dataset
                elif 'DATASET' in lines[i]:
                    dataset = name
                # get paper url
                collection['Paper'].append(url)
                i += 4

            # parse table
            elif lines[i][0] == '|' and i + 1 < len(lines) and \
                    lines[i + 1][:3] == '| :':
                cols = [col.strip() for col in lines[i].split('|')][1:-1]
                config_idx = cols.index('Arch')
                ckpt_idx = cols.index('ckpt')
                try:
                    flops_idx = cols.index('FLOPs')
                except ValueError:
                    flops_idx = -1
                try:
                    params_idx = cols.index('Params')
                except ValueError:
                    params_idx = -1
                metric_name_list, metric_idx_list = collate_metrics(cols)

                j = i + 2
                while j < len(lines) and lines[j][0] == '|':
                    line = lines[j].split('|')[1:-1]

                    if line[config_idx].find('](') == -1:
                        j += 1
                        continue
                    left = line[config_idx].index('](') + 2
                    right = line[config_idx].index(')', left)
                    config = line[config_idx][left:right].strip('./')

                    left = line[ckpt_idx].index('](') + 2
                    right = line[ckpt_idx].index(')', left)
                    ckpt = line[ckpt_idx][left:right]

                    model_name = osp.splitext(config)[0].replace(
                        'configs/', '', 1).replace('/', '--')

                    metadata = {'Training Data': dataset}
                    if flops_idx != -1:
                        metadata['FLOPs'] = float(line[flops_idx])
                    if params_idx != -1:
                        metadata['Parameters'] = float(line[params_idx])

                    metrics = {}
                    for metric_name, metric_idx in zip(metric_name_list,
                                                       metric_idx_list):
                        metrics[metric_name] = float(line[metric_idx])

                    model = {
                        'Name':
                        model_name,
                        'In Collection':
                        collection_name,
                        'Config':
                        config,
                        'Metadata':
                        metadata,
                        'Results': [{
                            'Task': task,
                            'Dataset': dataset,
                            'Metrics': metrics
                        }],
                        'Weights':
                        ckpt
                    }
                    models.append(model)
                    j += 1
                i = j

            else:
                i += 1

    result = {'Collections': [collection], 'Models': models}
    yml_file = md_file[:-2] + 'yml'

    is_different = dump_yaml_and_check_difference(result, yml_file)
    return is_different


def update_model_index():
    """Update model-index.yml according to model .md files.

    Returns:
        Bool: If the updated model-index.yml is different from the original.
    """
    configs_dir = osp.join(MMPOSE_ROOT, 'configs')
    yml_files = glob.glob(osp.join(configs_dir, '**', '*.yml'), recursive=True)
    yml_files.sort()

    model_index = {
        'Import':
        [osp.relpath(yml_file, MMPOSE_ROOT) for yml_file in yml_files]
    }
    model_index_file = osp.join(MMPOSE_ROOT, 'model-index.yml')
    is_different = dump_yaml_and_check_difference(model_index,
                                                  model_index_file)

    return is_different


if __name__ == '__main__':

    file_list = [fn for fn in sys.argv[1:] if osp.basename(fn) != 'README.md']

    if not file_list:
        exit(0)

    file_modified = False
    for fn in file_list:
        file_modified |= parse_md(fn)

    file_modified |= update_model_index()

    exit(1 if file_modified else 0)
