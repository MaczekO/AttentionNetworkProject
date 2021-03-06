import torch
from torch.utils.data import DataLoader
from utils import USGDataset
from model import ResidualAttentionModel_56, ResidualAttentionModel_92
from torchvision import transforms
import torch.optim as optim
import torch.nn as nn
from torch.utils.tensorboard import SummaryWriter
import tqdm
import pickle, copyreg

class ForkingPickler(pickle.Pickler):
    '''Pickler subclass used by multiprocessing.'''
    _extra_reducers = {}
    _copyreg_dispatch_table = copyreg.dispatch_table

    def __init__(self, *args):
        super().__init__(*args)
        self.dispatch_table = self._copyreg_dispatch_table.copy()
        self.dispatch_table.update(self._extra_reducers)

    @classmethod
    def register(cls, type, reduce):
        '''Register a reduce function for a type.'''
        cls._extra_reducers[type] = reduce

    @classmethod
    def dumps(cls, obj, protocol=4):
        buf = io.BytesIO()
        cls(buf, protocol).dump(obj)
        return buf.getbuffer()

    loads = pickle.loads

register = ForkingPickler.register

def dump(obj, file, protocol=4):
    '''Replacement for pickle.dump() using ForkingPickler.'''
    ForkingPickler(file, protocol).dump(obj)

if __name__ == "__main__":
    writer = SummaryWriter()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if torch.cuda.is_available():
        print("Using GPU")

    training_transforms = transforms.Compose([
        transforms.ToPILImage(),
        transforms.RandomCrop(224),
        transforms.ToTensor(),
    ])

    testing_transforms = transforms.Compose([
        transforms.ToPILImage(),
        transforms.FiveCrop(224),
        transforms.Lambda(lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
    ])

    train_dataset = USGDataset("train_dataset.pkl", training_transforms)
    val_dataset = USGDataset("validation_dataset.pkl", testing_transforms)

    train_dataloader = DataLoader(train_dataset, 16, shuffle=True, num_workers=0)
    test_dataloader = DataLoader(val_dataset, 16, shuffle=False, num_workers=0)

    net = ResidualAttentionModel_56()
    net.to(device)

    criterion = nn.BCELoss()
    optimizer = optim.SGD(net.parameters(), lr=0.005, momentum=0.9, nesterov=True, weight_decay=0.0001)
    scheduler = optim.lr_scheduler.MultiStepLR(optimizer, milestones=[100, 200, 250], gamma=0.1)

    for epoch in tqdm.tqdm(range(300)):  # loop over the dataset multiple times
        running_loss = 0.0
        for i, data in enumerate(train_dataloader, 0):
            inputs = data['image'].to(device)
            labels = data['label'].float().to(device)

            optimizer.zero_grad()

            outputs = net(inputs).view(-1)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            if i % 10 == 9:
                writer.add_scalar("Loss/train", running_loss/10, i+epoch*len(train_dataloader))
                running_loss = 0.0

        number = 0
        loss_sum = 0
        total = 0
        correct = 0
        with torch.no_grad():
            for i, data in enumerate(test_dataloader, 0):
                inputs = data['image'].to(device)
                labels = data['label'].float().to(device)
                bs, ncrops, c, h, w = inputs.size()
                result = net(inputs.view(-1, c, h, w))
                result_avg = result.view(bs, ncrops, -1).mean(1)
                loss = criterion(result_avg.view(-1), labels)
                predicted = torch.round(result_avg.view(-1))
                number += 1
                loss_sum += loss.item()
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
        writer.add_scalar("Loss/test", running_loss/number, epoch)
        writer.add_scalar("Accuracy/test", correct/total, epoch)

    PATH = './Res_56_new.pth'
    torch.save(net.state_dict(), PATH)

