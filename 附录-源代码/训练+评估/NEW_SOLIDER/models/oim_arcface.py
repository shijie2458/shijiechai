import torch
import torch.nn.functional as F
from torch import autograd, nn
import math
# from utils.distributed import tensor_gather


class OIM(autograd.Function):
    @staticmethod
    def forward(ctx, inputs, targets, lut, cq, header, momentum):
        ctx.save_for_backward(inputs, targets, lut, cq, header, momentum)
        outputs_labeled = inputs.mm(lut.t())
        outputs_unlabeled = inputs.mm(cq.t())
        return torch.cat([outputs_labeled, outputs_unlabeled], dim=1)

    @staticmethod
    def backward(ctx, grad_outputs):
        inputs, targets, lut, cq, header, momentum = ctx.saved_tensors

        # inputs, targets = tensor_gather((inputs, targets))

        grad_inputs = None
        if ctx.needs_input_grad[0]:
            grad_outputs = grad_outputs.to(torch.half)
            lutt = lut.to(torch.half)
            cqq = cq.to(torch.half)
            grad_inputs = grad_outputs.mm(torch.cat([lutt, cqq], dim=0))
            if grad_inputs.dtype == torch.float16:
                grad_inputs = grad_inputs.to(torch.float32)

        for x, y in zip(inputs, targets):
            if y < len(lut):
                lut[y] = momentum * lut[y] + (1.0 - momentum) * x
                lut[y] /= lut[y].norm()
            else:
                cq[header] = x
                header = (header + 1) % cq.size(0)
        return grad_inputs, None, None, None, None, None


def oim(inputs, targets, lut, cq, header, momentum=0.5):
    return OIM.apply(inputs, targets, lut, cq, torch.tensor(header), torch.tensor(momentum))


class OIMLoss(nn.Module):
    def __init__(self, num_features, num_pids, num_cq_size, oim_momentum, oim_scalar, arcface_loss_weight, cosine):
        super(OIMLoss, self).__init__()
        self.num_features = num_features
        self.num_pids = num_pids
        self.num_unlabeled = num_cq_size
        self.momentum = oim_momentum
        self.oim_scalar = oim_scalar

        self.register_buffer("lut", torch.zeros(self.num_pids, self.num_features))
        self.register_buffer("cq", torch.zeros(self.num_unlabeled, self.num_features))

        self.header_cq = 0

        # self.s = 30                         # 原文64，scalar30
        # self.arcface_loss_weight = 0.05
        # self.cosine = 0.6
        self.arcface_loss_weight = arcface_loss_weight
        self.cosine = cosine


    def forward(self, inputs, roi_label):
        # merge into one batch, background label = 0
        targets = torch.cat(roi_label)
        label = targets - 1  # background label = -1

        inds = label >= 0
        label = label[inds]
        inputs = inputs[inds.unsqueeze(1).expand_as(inputs)].view(-1, self.num_features)
        # print('inputs', inputs.shape)
        # print('label', label.shape)
        projected = oim(inputs, label, self.lut, self.cq, self.header_cq, momentum=self.momentum)
        # print('projected', projected.shape)
        cosine = projected
        # m = torch.zeros(label.size()[0], cosine.size()[1], device=cosine.device)         #SYSU数据集
        m = torch.zeros(label.size()[0], 6000, device=cosine.device)                    #PRW数据集,构建角度矩阵m
        m.scatter_(1, label.reshape(-1, 1), self.cosine)#矩阵m填充角度0.5
        # print('m.scatter',m)
        # print('m.scatter.shape', m.shape)
        m = m[:, :cosine.size()[1]]#获取cosine张量的第二个维度的大小。
        theta = cosine.acos()#求反余弦
        # print('th',theta)
        theta_m = torch.clamp(theta+m, min=1e-3, max=math.pi-1e-3)#反余弦加上角度矩阵m
        cosine = theta_m.cos()
        cosine = self.oim_scalar*cosine
        loss_arc = F.cross_entropy(cosine, label, ignore_index=5554)  # 为什么忽略5554


        projected *= self.oim_scalar

        self.header_cq = (
            self.header_cq + (label >= self.num_pids).long().sum().item()
        ) % self.num_unlabeled
        loss_oim = F.cross_entropy(projected, label, ignore_index=5554)
        #loss加和
        # loss = self.arcface_loss_weight * loss_arc + (1-self.arcface_loss_weight) * loss_oim
        loss = self.arcface_loss_weight * loss_arc + loss_oim
        return loss, inputs, label
