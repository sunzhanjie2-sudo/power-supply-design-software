import control as ct
import numpy as np

class Compensator3P3Z:
    def __init__(self, KP, fz1, fz2, fp1, fp2):
        self.s = ct.tf('s')
        self.KP = KP
        self.wz1 = 2 * np.pi * fz1
        self.wz2 = 2 * np.pi * fz2
        self.wp1 = 2 * np.pi * fp1
        self.wp2 = 2 * np.pi * fp2
    
    def get_transfer_function(self):
        Gc = self.KP * (1 + self.s / self.wz1) * (1 + self.s / self.wz2) / self.s / (1 + self.s / self.wp1) / (1 + self.s / self.wp2)
        return Gc

class Compensator2P2Z:
    def __init__(self, KP, fz, fp):
        self.s = ct.tf('s')
        self.KP = KP
        self.wz = 2 * np.pi * fz
        self.wp = 2 * np.pi * fp
    
    def get_transfer_function(self):
        Gc = self.KP * (1 + self.s / self.wz) / self.s / (1 + self.s / self.wp)
        return Gc