import pandas as pd
import matplotlib.pyplot
import numpy as np


def add_or_create(d, k, v=1):
    if k in d:
        d[k] += v
    else:
        d[k] = v


data = pd.read_csv('~/PycharmProjects/PaStA/resources/linux/resources/characteristics_subsystem.csv')
data.set_index('subsystem', inplace=True)

#data = data[(data['total'] > 1000)]# & (data['total'] < 800000)]
data = data[(data['ignored'] > 100)]
#data = data[~data['status'].isin(['maintained', 'supported'])]
#data = data[data['status'].isin(['orphan; obsolete', 'orphan', 'obsolete', 'odd fixes'])]
print(len(data))

orphnd = 0
for s, stats in data.iterrows():
    if stats['status'] in ['orphan; obsolete', 'orphan', 'obsolete', 'odd fixes']:
        orphnd += 1
print(orphnd)

ratios = pd.DataFrame()

for h in list(data):
    if 'total' == h:
        continue
    if 'total' in h:
        s = h.split('v')
        if s[1][0] == '2':
            continue
        k = s[1]
        if len(s[1]) is 3:
            k = s[1].split('.')
            k[1] = '0' + k[1]
            k = '.'.join(k)

        data['v'.join(['ignored', s[1]])].fillna(0, inplace=True)
        # data['v'.join(['total', s[1]])].fillna(0, inplace=True)
        ratios[k] = data['v'.join(['ignored', s[1]])] / data['v'.join(['total', s[1]])]
        # ratios[k] = data['v'.join(['total', s[1]])]

ratios = ratios.T.sort_index().T

ratio = data['ignored'].fillna(0) / data['total']

print('')
print('---------------------------')
print('quantile by ratio')
q = list(ratio.quantile([.25, .75]))

lower_quantile = []
higher_quantile = []

for subsystem, r in ratio.items():
    if r < q[0]:
        lower_quantile.append(subsystem)
    elif r > q[1]:
        higher_quantile.append(subsystem)

print('Lower (' + str(len(lower_quantile)) + '): ' + str(lower_quantile))
print('Higher (' + str(len(higher_quantile)) + '): ' + str(higher_quantile))

lower_quantile_status = 0
for s in lower_quantile:
    if data['status'][s] in ['orphan; obsolete', 'orphan', 'obsolete', 'odd fixes']:
        lower_quantile_status += 1
print(lower_quantile_status)

higher_quantile_status = 0
for s in higher_quantile:
    if data['status'][s] in ['orphan; obsolete', 'orphan', 'obsolete', 'odd fixes']:
        higher_quantile_status += 1
print(higher_quantile_status)

print('')
print('---------------------------')
print('quantile by steepness')

res = []
for index, row in ratios.iterrows():
    row_tmp = row.reset_index(drop=True).dropna()
    if len(row_tmp) < 2:
        continue
    row = row_tmp
    res.append((index, np.polyfit(list(row.index), list(row), 1)[0]))

res = pd.Series(dict(res))
steep_quantile = list(res.quantile([.25, .75]))
max = res.max()
min = res.min()
lower_quantile = []
higher_quantile = []

for k, v in res.items():
    if v < steep_quantile[0]:
        lower_quantile.append(k)
    elif v > steep_quantile[1]:
        higher_quantile.append(k)

print('Lower (' + str(len(lower_quantile)) + '): ' + str(lower_quantile))
print('Higher (' + str(len(higher_quantile)) + '): ' + str(higher_quantile))

lower_quantile_status = 0
for s in lower_quantile:
    if data['status'][s] in ['orphan; obsolete', 'orphan', 'obsolete', 'odd fixes']:
        lower_quantile_status += 1
print(lower_quantile_status)

higher_quantile_status = 0
for s in higher_quantile:
    if data['status'][s] in ['orphan; obsolete', 'orphan', 'obsolete', 'odd fixes']:
        higher_quantile_status += 1
print(higher_quantile_status)

'''
ratios = ratios.loc[['THE REST', 'VOLTAGE AND CURRENT REGULATOR FRAMEWORK', 'ARM SUB-ARCHITECTURES']]
ax = ratios.T.plot(subplots=True, legend=None)
matplotlib.pyplot.show()

groups = data.groupby(['status'])

for name, group in groups:
    print(name + ': ' + (str(group['ignored'].sum() / group['total'].sum())))
'''

print('')
print('---------------------------')
print('new/old')

new = []
old = []
for subsystem, stats in ratios.iterrows():
    if stats[['3.00', '3.01', '3.02', '3.03', '3.04']].apply(lambda x: np.isnan(x)).all():
        new.append(subsystem)
    elif stats[['4.16', '4.17', '4.18', '4.19', '4.20']].apply(lambda x: np.isnan(x)).all():
        old.append(subsystem)

print('New (' + str(len(new)) + '): ' + str(new))

ratios_tmp = ratios.loc[['THE REST'] + new]
ax = ratios_tmp.T.plot(subplots=True, legend=None)
matplotlib.pyplot.show()

print('old (' + str(len(old)) + '): ' + str(old))

ratios_tmp = ratios.loc[['THE REST'] + old]
ax = ratios_tmp.T.plot(subplots=True, legend=None)
matplotlib.pyplot.show()


'''
# clean
ratios.dropna(inplace=True, thresh=20)
print(len(ratios))


#ratios = ratios.loc[['THE REST', 'PCI SUBSYSTEM']]
#ax = ratios.T.plot(subplots=True, legend=None)
#matplotlib.pyplot.show()

min = ratios.loc['THE REST'].min()
max = ratios.loc['THE REST'].max()
mean = ratios.loc['THE REST'].mean()

print('Min: ' + str (min) + ' mean: ' + str (mean) + ' max: ' + str (max))
minl = []
avgl = []
maxl = []
for index, row in ratios.iterrows():
    if min > row.mean():
        minl.append(index)
    elif max < row.mean():
        maxl.append(index)
    else:
        avgl.append(index)

print('Min: ' + str(len(minl)))
print(minl)
print('Avg: ' + str(len(avgl)))
print(avgl)
print('Max: ' + str(len(maxl)))
print(maxl)

data.set_index('subsystem', inplace=True)

for s in maxl:
    print(s)
    print(data.loc[s]['status'])
    print(data.loc[s]['total'])
    print(data.loc[s]['ignored'])
    print()
    '''
