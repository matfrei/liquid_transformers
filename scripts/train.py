import os
import argparse

import numpy as np

from datasets import load_metric

import torch

from transformers import TrainingArguments, Trainer

from layershuffle.utils import Experiment, parse_preprocessor, parse_model, parse_dataset, get_cfg_defaults

metric = load_metric("accuracy")


def compute_metrics(p):
    return metric.compute(predictions=np.argmax(p.predictions, axis=1), references=p.label_ids)

def collate_fn(batch):
    return {
        'pixel_values': torch.stack([x[0] for x in batch]),
        'labels': torch.tensor([x[1] for x in batch])
    }

def parse_args():
    parser = argparse.ArgumentParser(
        prog='train',
        description='Train a model',
        epilog='')
    parser.add_argument('--config-path', help='path to config file')
    args = parser.parse_args()
    return args

def train_model(config,save_model=True,use_bf=False): 
    config.freeze()

    experiment = Experiment(config.EXPERIMENT_LOG.BASEPATH, config.EXPERIMENT_LOG.MODEL_NAME, config.EXPERIMENT_LOG.EXPERIMENT_NAME)

    device = torch.device(f'cuda:{config.GPU_ID}') if torch.cuda.is_available() else torch.device("cpu")
    processor = parse_preprocessor(config)

    train_set,val_set = parse_dataset(config,processor)

    save_total_limit=0
    if save_model:
        save_total_limit=2
    
    for seed in range(config.RANDOM_SEED,config.RANDOM_SEED+config.NUM_RUNS):
        training_args = TrainingArguments(
            output_dir=os.path.join(experiment.modelpath,f"run_{seed}"),
            seed=seed,
            data_seed=seed,
            per_device_train_batch_size=config.OPTIMIZER.BATCH_SIZE_TRAIN,#432 for single gpu, 320 for 4x
            per_device_eval_batch_size=config.OPTIMIZER.BATCH_SIZE_EVAL, # 10x train batch size
            evaluation_strategy="epoch",
            save_strategy="epoch",
            num_train_epochs=config.OPTIMIZER.EPOCHS,
            fp16=not use_bf,
            bf16=use_bf,
            logging_strategy="epoch",
            learning_rate=config.OPTIMIZER.LR,
            save_total_limit=save_total_limit,
            remove_unused_columns=False,
            push_to_hub=False,
            report_to='tensorboard',
            load_best_model_at_end=True,
            dataloader_num_workers=config.N_WORKERS)

        model = parse_model(config)
        model.to(device)

        trainer = Trainer(
            model=model,
            args=training_args,
            data_collator=collate_fn,
            compute_metrics=compute_metrics,
            train_dataset=train_set,
            eval_dataset=val_set,
            tokenizer=processor,
        )

        train_results = trainer.train()
        if save_model:
            trainer.save_model()
            trainer.log_metrics("train", train_results.metrics)
            trainer.save_metrics("train", train_results.metrics)
            trainer.save_state()
            
        return trainer

if __name__ == '__main__':
    config_path = parse_args().config_path
    config = get_cfg_defaults()
    config.merge_from_file(config_path)
    train_model(config)
