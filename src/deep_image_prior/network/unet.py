# -*- coding: utf-8 -*-
import torch
import torch.nn as nn
import numpy as np
from .scale_module import get_scale_modules

def get_unet_model(in_ch=1, out_ch=1, scales=5,
                   channels=(32, 32, 64, 64, 128, 128), use_sigmoid=True,
                   use_norm=True, norm_type='group'):
    assert (1 <= scales <= 6)
    skip_channels = [0, 0, 0, 0, 4, 4]
    return UNet(in_ch=in_ch, out_ch=out_ch, channels=channels[:scales],
                skip_channels=skip_channels, use_sigmoid=use_sigmoid,
                use_norm=use_norm, norm_type=norm_type)

class UNet(nn.Module):
    def __init__(self, in_ch, out_ch, channels, skip_channels,
                 use_sigmoid=True, use_norm=True, norm_type='group',
                 use_scale_in_layer=False, use_scale_out_layer=False,
                 scaling_kwargs=None):
        super(UNet, self).__init__()
        assert (len(channels) == len(skip_channels))
        assert norm_type in ['group', 'batch']
        self.scales = len(channels)
        self.use_sigmoid = use_sigmoid
        self.down = nn.ModuleList()
        self.up = nn.ModuleList()
        self.inc = InBlock(in_ch, channels[0], use_norm=use_norm, norm_type=norm_type)
        for i in range(1, self.scales):
            self.down.append(DownBlock(in_ch=channels[i - 1],
                                       out_ch=channels[i],
                                       use_norm=use_norm, norm_type=norm_type))
        for i in range(1, self.scales):
            self.up.append(UpBlock(in_ch=channels[-i],
                                   out_ch=channels[-i - 1],
                                   skip_ch=skip_channels[-i],
                                   use_norm=use_norm, norm_type=norm_type))
        self.outc = OutBlock(in_ch=channels[0],
                             out_ch=out_ch)
        self.use_scale_in_layer = use_scale_in_layer
        self.use_scale_out_layer = use_scale_out_layer
        if self.use_scale_in_layer or self.use_scale_out_layer:
            self.scale_in, self.scale_out = get_scale_modules(1, out_ch,
                                                              **scaling_kwargs)

    def forward(self, x0):
        if self.use_scale_in_layer:
            if x0.shape[1] == 1:
                x0 = self.scale_in(x0)
            elif x0.shape[1] == 2:
                x0 = torch.cat((self.scale_in(x0[:, 0].unsqueeze(dim=1)), x0[:, 1].unsqueeze(dim=1)), dim=1)
            else:
                raise KeyError
        xs = [self.inc(x0), ]
        for i in range(self.scales - 1):
            xs.append(self.down[i](xs[-1]))
        x = xs[-1]
        for i in range(self.scales - 1):
            x = self.up[i](x, xs[-2 - i])

        x = self.outc(x)

        if self.use_sigmoid and self.use_scale_out_layer:
            raise ValueError('Cannot use both output scaling layer and sigmoid '
                             'output activation; please set either '
                             'use_scale_out_layer=False or use_sigmoid=False.')

        if self.use_sigmoid:
            return torch.sigmoid(x)
        elif self.use_scale_out_layer:
            return self.scale_out(x)
        else:
            return x

class DownBlock(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size=3, num_groups=4, use_norm=True, norm_type='group'):
        super(DownBlock, self).__init__()
        to_pad = int((kernel_size - 1) / 2)
        if use_norm:
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size,
                          stride=2, padding=to_pad),
                (nn.GroupNorm(num_channels=out_ch, num_groups=num_groups) if norm_type == 'group' else nn.BatchNorm2d(num_features=out_ch)),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(out_ch, out_ch, kernel_size,
                          stride=1, padding=to_pad),
                (nn.GroupNorm(num_channels=out_ch, num_groups=num_groups) if norm_type == 'group' else nn.BatchNorm2d(num_features=out_ch)),
                nn.LeakyReLU(0.2, inplace=True))
        else:
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size,
                          stride=2, padding=to_pad),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(out_ch, out_ch, kernel_size,
                          stride=1, padding=to_pad),
                nn.LeakyReLU(0.2, inplace=True))

    def forward(self, x):
        x = self.conv(x)
        return x


class InBlock(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size=3, num_groups=2, use_norm=True, norm_type='group'):
        super(InBlock, self).__init__()
        to_pad = int((kernel_size - 1) / 2)
        if use_norm:
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size,
                          stride=1, padding=to_pad),
                (nn.GroupNorm(num_channels=out_ch, num_groups=num_groups) if norm_type == 'group' else nn.BatchNorm2d(num_features=out_ch)),
                nn.LeakyReLU(0.2, inplace=True))
        else:
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size,
                          stride=1, padding=to_pad),
                nn.LeakyReLU(0.2, inplace=True))

    def forward(self, x):
        x = self.conv(x)
        return x


class UpBlock(nn.Module):
    def __init__(self, in_ch, out_ch, skip_ch=4, kernel_size=3, num_groups=2, use_norm=True, norm_type='group'):
        super(UpBlock, self).__init__()
        to_pad = int((kernel_size - 1) / 2)
        self.skip = skip_ch > 0
        if skip_ch == 0:
            skip_ch = 1
        if use_norm:
            self.conv = nn.Sequential(
                (nn.GroupNorm(num_channels=in_ch + skip_ch, num_groups=1) if norm_type == 'group' else nn.BatchNorm2d(num_features=in_ch + skip_ch)), #LayerNorm
                nn.Conv2d(in_ch + skip_ch, out_ch, kernel_size, stride=1,
                          padding=to_pad),
                (nn.GroupNorm(num_channels=out_ch, num_groups=num_groups) if norm_type == 'group' else nn.BatchNorm2d(num_features=out_ch)),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(out_ch, out_ch, kernel_size,
                          stride=1, padding=to_pad),
                (nn.GroupNorm(num_channels=out_ch, num_groups=num_groups) if norm_type == 'group' else nn.BatchNorm2d(num_features=out_ch)),
                nn.LeakyReLU(0.2, inplace=True))
        else:
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch + skip_ch, out_ch, kernel_size, stride=1,
                          padding=to_pad),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(out_ch, out_ch, kernel_size,
                          stride=1, padding=to_pad),
                nn.LeakyReLU(0.2, inplace=True))

        if use_norm:
            self.skip_conv = nn.Sequential(
                nn.Conv2d(out_ch, skip_ch, kernel_size=1, stride=1),
                (nn.GroupNorm(num_channels=skip_ch, num_groups=1) if norm_type == 'group' else nn.BatchNorm2d(num_features=skip_ch)), #LayerNorm
                nn.LeakyReLU(0.2, inplace=True))
        else:
            self.skip_conv = nn.Sequential(
                nn.Conv2d(out_ch, skip_ch, kernel_size=1, stride=1),
                nn.LeakyReLU(0.2, inplace=True))

        self.up = nn.Upsample(scale_factor=2, mode='bilinear',
                              align_corners=True)
        self.concat = Concat()

    def forward(self, x1, x2):
        x1 = self.up(x1)
        x2 = self.skip_conv(x2)
        if not self.skip:
            x2 = x2 * 0
        x = self.concat(x1, x2)
        x = self.conv(x)
        return x


class Concat(nn.Module):
    def __init__(self):
        super(Concat, self).__init__()

    def forward(self, *inputs):
        inputs_shapes2 = [x.shape[2] for x in inputs]
        inputs_shapes3 = [x.shape[3] for x in inputs]

        if (np.all(np.array(inputs_shapes2) == min(inputs_shapes2)) and
                np.all(np.array(inputs_shapes3) == min(inputs_shapes3))):
            inputs_ = inputs
        else:
            target_shape2 = min(inputs_shapes2)
            target_shape3 = min(inputs_shapes3)

            inputs_ = []
            for inp in inputs:
                diff2 = (inp.size(2) - target_shape2) // 2
                diff3 = (inp.size(3) - target_shape3) // 2
                inputs_.append(inp[:, :, diff2: diff2 + target_shape2,
                                   diff3:diff3 + target_shape3])
        return torch.cat(inputs_, dim=1)


class OutBlock(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(OutBlock, self).__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, kernel_size=1, stride=1)

    def forward(self, x):
        x = self.conv(x)
        return x

    def __len__(self):
        return len(self._modules)
