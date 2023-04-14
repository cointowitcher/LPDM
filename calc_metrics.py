# Must run from within the scripts directory
from skimage.metrics import structural_similarity, peak_signal_noise_ratio, mean_squared_error
from skimage.io import imread
import glob, os, sys
from omegaconf import OmegaConf
import numpy as np
from tqdm import tqdm
import lpips, torch, cv2
from functools import partial
import pandas as pd
import pyiqa
import shutil
import argparse
sys.path.append(os.path.abspath(os.path.join('external', 'taming-transformers')))
sys.path.append(os.path.abspath(os.path.join('external', 'clip')))


class FullReferenceMeasure():
    def __init__(self, net='alex', use_gpu=False):
        self.device = 'cuda' if use_gpu else 'cpu'
        self.model = lpips.LPIPS(net=net)
        self.model.to(self.device)

        self.metrics = {
            'ssim' : partial(self.ssim, is_gray=False),
            'ssim_grayscale' : partial(self.ssim, is_gray=True),
            'psnr' : self.psnr,
            'mae' : self.mae,
            'lpips' : self.lpips
        }
        
    def get_empty_metrics(self):
        d = {}
        for k in self.metrics.keys():
            d[k] = []
        return d

    def measure(self, imgA, imgB):
        return {name: float(func(imgA, imgB)) for name, func in self.metrics.items()}
    
    def t_to_lpips(self, img):
        assert len(img.shape) == 3
        assert img.dtype == np.uint8
        img = np.transpose(img, [2, 0, 1])
        img = np.expand_dims(img, axis=0)
        return torch.tensor(img) / 127.5 - 1
        
    def lpips(self, imgA, imgB, model=None):
        tA = self.t_to_lpips(imgA).to(self.device)
        tB = self.t_to_lpips(imgB).to(self.device)
        dist01 = self.model.forward(tA, tB).item()
        return dist01

    def ssim(self, imgA, imgB, is_gray=False):
        if is_gray:
            return structural_similarity(cv2.cvtColor(imgA, cv2.COLOR_RGB2GRAY), cv2.cvtColor(imgB, cv2.COLOR_RGB2GRAY))
        else:
            return structural_similarity(imgA, imgB, channel_axis=-1) # For colour images

    def psnr(self, imgA, imgB):
        return peak_signal_noise_ratio(imgA, imgB) 
    
    def mae(self, imgA, imgB):
        return np.mean(np.absolute((imgA / 255.0 - imgB / 255.0)))
    
class NoReferenceMeasure():
    def __init__(self, use_gpu=False):
        device = torch.device('cuda') if use_gpu else torch.device('cpu') 

        self.metrics = {
            'niqe' : pyiqa.create_metric('niqe', device=device),
            'brisque' : pyiqa.create_metric('brisque', device=device),
            'pi' : pyiqa.create_metric('pi', device=device),
            'musiq-spaq' : pyiqa.create_metric('musiq-spaq', device=device),
        }
        
    def get_empty_metrics(self):
        d = {}
        for k in self.metrics.keys():
            d[k] = []
        return d

    def measure(self, pred_path):
        return {name: float(func(pred_path)) for name, func in self.metrics.items()}

def get_metrics(target_path, pred_path):

    BASE_PATH = 'configs/test/metrics.yaml'
    NO_SKIP = True

    print(f'Scanning configs...')
    results_csv = 'test/results.csv'

    fr = FullReferenceMeasure()
    nr = NoReferenceMeasure()

    # for config_path in glob.glob('../configs/metrics/**/*.yaml', recursive=True):    
    config_path = BASE_PATH

    if not NO_SKIP and os.path.isfile(results_csv):
        current_results = pd.read_csv(results_csv, index_col='file') 
        if os.path.basename(config_path) in current_results.index:
            print(f'Skipping: {os.path.basename(config_path)}')
            exit()

    print(f'Calculating metrics: {os.path.basename(config_path)}')
    config = OmegaConf.load(config_path)
    pred_paths = glob.glob(pred_path)

    results_fr = {}
    results_nr= {}

    if target_path:
        target_paths = glob.glob(target_path)
        assert len(pred_paths) == len(target_paths), f"Number of images in folders to not match {len(pred_paths)} != {len(target_paths)}"
        for p, y in zip(pred_paths, target_paths):
            assert os.path.splitext(os.path.basename(p))[0] == os.path.splitext(os.path.basename(y))[0] # Ignore extension

        results_fr = fr.get_empty_metrics()
        for p_path, y_path  in tqdm(zip(pred_paths, target_paths)):
            # p, y = imread(p_path, as_gray=True), imread(y_path, as_gray=True)
            p, y = imread(p_path), imread(y_path)
            metrics = fr.measure(p,y)
            for k,v in metrics.items():
                results_fr[k].append(v)

    if not target_path:
        results_nr = nr.get_empty_metrics()
        # Not calculating NR metrics for paired data
        for p_path in tqdm(pred_paths):
            metrics = nr.measure(p_path) # Uses paths and not np arrays
            for k,v in metrics.items():
                results_nr[k].append(v)

    all_metrics = {**results_fr, **results_nr}
    del all_metrics['ssim_grayscale']
    return all_metrics

if __name__ == '__main__':
    get_metrics('test/dark/*.png', 'test/denoised/*.png')