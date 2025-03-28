import torch

from utils.transforms import build_transforms
from utils.utils import create_small_table

from .cuhk_sysu import CUHKSYSU
from .prw import PRW

# 打印关于数据集的一些统计信息
def print_statistics(dataset):
    """
    Print dataset statistics.
    """
    num_imgs = len(dataset.annotations)
    num_boxes = 0
    pid_set = set()
    for anno in dataset.annotations:
        num_boxes += anno["boxes"].shape[0]
        for pid in anno["pids"]:
            pid_set.add(pid)
    statistics = {
        "dataset": dataset.name,
        "split": dataset.split,
        "num_images": num_imgs,
        "num_boxes": num_boxes,
    }
    if dataset.name != "CUHK-SYSU" or dataset.split != "query":
        pid_list = sorted(list(pid_set))
        if dataset.split == "query":
            num_pids, min_pid, max_pid = len(pid_list), min(pid_list), max(pid_list)
            statistics.update(
                {
                    "num_labeled_pids": num_pids,
                    "min_labeled_pid": int(min_pid),
                    "max_labeled_pid": int(max_pid),
                }
            )
        else:
            unlabeled_pid = pid_list[-1]
            pid_list = pid_list[:-1]  # remove unlabeled pid
            num_pids, min_pid, max_pid = len(pid_list), min(pid_list), max(pid_list)
            statistics.update(
                {
                    "num_labeled_pids": num_pids,
                    "min_labeled_pid": int(min_pid),
                    "max_labeled_pid": int(max_pid),
                    "unlabeled_pid": int(unlabeled_pid),
                }
            )
    print(f"=> {dataset.name}-{dataset.split} loaded:\n" + create_small_table(statistics))


def build_dataset(dataset_name, root, transforms, split, verbose=True):     # 数据集划分split
    if dataset_name == "CUHK-SYSU":
        dataset = CUHKSYSU(root, transforms, split)
    elif dataset_name == "PRW":
        dataset = PRW(root, transforms, split)
    else:
        raise NotImplementedError(f"Unknow dataset: {dataset_name}")
    if verbose:
        print_statistics(dataset)
    return dataset

#将批次数据重新组织成多个元组
def collate_fn(batch):
    return tuple(zip(*batch))


def build_train_loader(cfg):
    transforms = build_transforms(is_train=True)
    dataset = build_dataset(cfg.INPUT.DATASET, cfg.INPUT.DATA_ROOT, transforms, "train")
    return torch.utils.data.DataLoader(
        dataset,
        batch_size=cfg.INPUT.BATCH_SIZE_TRAIN,
        shuffle=True,                               # 数据将被随机洗混，即数据的顺序会被打
        num_workers=cfg.INPUT.NUM_WORKERS_TRAIN,
        pin_memory=True,                            # 将加载的数据复制到 CUDA 固定的内存中，这可以提高数据传输速度
        drop_last=True,                             # 如果最后一个批次的数据数量不足一个完整的批次，它将被丢弃
        collate_fn=collate_fn,
    )


def build_test_loader(cfg):
    transforms = build_transforms(is_train=False)
    gallery_set = build_dataset(cfg.INPUT.DATASET, cfg.INPUT.DATA_ROOT, transforms, "gallery")
    query_set = build_dataset(cfg.INPUT.DATASET, cfg.INPUT.DATA_ROOT, transforms, "query")
    gallery_loader = torch.utils.data.DataLoader(
        gallery_set,
        batch_size=cfg.INPUT.BATCH_SIZE_TEST,
        shuffle=False,
        num_workers=cfg.INPUT.NUM_WORKERS_TEST,
        pin_memory=True,
        collate_fn=collate_fn,
    )
    query_loader = torch.utils.data.DataLoader(
        query_set,
        batch_size=cfg.INPUT.BATCH_SIZE_TEST,
        shuffle=False,
        num_workers=cfg.INPUT.NUM_WORKERS_TEST,
        pin_memory=True,
        collate_fn=collate_fn,
    )
    return gallery_loader, query_loader
