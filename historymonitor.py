import matplotlib.pyplot as plt
import matplotlib.animation as animation
import pandas as pd
from random import random
import sys
import numpy as np
import matplotlib as mpl
import subprocess
import math
import getopt
import threading
import queue

# python historymonitor.py -w10 --height=10 -rCall,pwr,sm --interval=2

interval = 5  # seconds between updates
width=6  #inches
height=3
samples = 60  # number of samples in history
# column labels that will be reported
useheader = ["CPU","pwr","gtemp","sm","mem"]
numproc = 8 # number of processors reported by sar

full_cmd_arguments = sys.argv
argument_list = full_cmd_arguments[1:]
short_options = "i:w:h:s:r:"
long_options = ["interval=", "width=", "height=","samples=","report="]
try:
    arguments, values = getopt.getopt(argument_list, short_options, long_options)
except getopt.error as err:
    # Output error, and return with an error code
    print (str(err))
    sys.exit(2)

for current_argument, current_value in arguments:
    if current_argument in ("-i", "--interval"):
        interval = int(current_value)
    elif current_argument in ("-w", "--width"):
        width = float(current_value)
    elif current_argument in ("-h", "--height"):
        height = float(current_value)
    elif current_argument in ("-s", "--samples"):
        samples = int(current_value)
    elif current_argument in ("-r", "--report"):
        useheader = current_value.split(",")


## code for reading nvidia dmon
def initGPUpipe(interval):
    nvidiaproc = subprocess.Popen(["nvidia-smi","dmon -i 1 -o T -d "+str(interval) ],
                           shell=True,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    header = str(nvidiaproc.stdout.readline()).split() # get header
    t = nvidiaproc.stdout.readline().split()  # skip type information
    gpudata = pd.DataFrame(columns=header)  # create data frame with header
#    print(gpudata)
    return gpudata, nvidiaproc

def getnewdatagpu(nvidiaproc,q):
    # read nvidia data skipping headers that are occasionally printed
    while True:
        raw = nvidiaproc.stdout.readline() 
        line = str( raw ).split()
        date = line[1]
        dateparts = date.split(":")
#        print("gpudate",dateparts)
        if len(dateparts) > 2 and dateparts[0] != "HH": 
           line = line[1:]
           q.put( line )

## code for reading cpu
def initCPUpipe(interval):
    sarproc = subprocess.Popen(["sar","-P ALL","-u "+str(interval)],
                           shell=True,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    # sar outputs separate line for each processor, so change into one line with all processors
    line = str(sarproc.stdout.readline()).split()
    line = sarproc.stdout.readline().split()
    newline = ""
    lastproc = ""
    line = [" ","",""]
    while len(line) > 1:
        line = str(sarproc.stdout.readline()).split()
        if len(line) > 1:
            newline = newline +" C"+ line[2]
            lastproc = line[2] # label for last cpu processor
    header = newline.split()
    header[1]="CPU"
    print(header)
    cpudata = pd.DataFrame(columns=header)
    return cpudata, sarproc, lastproc

def getnewdatacpu(sarproc,q):
    newline = ""
    date = ":"
    while True:
        line = str(sarproc.stdout.readline()).split()
#        print("sar",line)
        date = str(line[0])
        if len(line) > 3:
            newline = newline +" "+ line[3]
            if line[2] == lastproc: 
                newparts = newline.split()
                newparts[0] = date
#                print("sar",newparts)
                q.put( newparts )

## combine gpu and cpu headers
cpudata, sarproc, lastproc = initCPUpipe(interval)
gpudata, nvidiaproc = initGPUpipe(interval)
data = pd.concat([cpudata,gpudata],axis=1)
cpudatalen = len(cpudata.columns)
gpudatalen = len(gpudata.columns)

# threads and queues are used to keep two pipes synchronized, otherwise there is a lag
pa_q = queue.Queue()
pb_q = queue.Queue()

# start a pair of threads to read output from procedures A and B
pa_t = threading.Thread(target=getnewdatacpu, args=(sarproc,pa_q))
pb_t = threading.Thread(target=getnewdatagpu, args=(nvidiaproc,pb_q))
pa_t.daemon = True
pb_t.daemon = True
pa_t.start()
pb_t.start()


## figure parameters
barcolor = ['r','b','g','m','y','c']
mpl.rcParams['toolbar'] = 'None'
numfig = len(useheader)
fig = plt.figure(figsize=(width,height))
fig.canvas.set_window_title('CPU/GPU monitor')
axlist = [fig.add_subplot(numfig, 1, i+1) for i in range(numfig)]
plt.subplots_adjust(left=0.1, right=0.9, top=0.95, bottom=0.05)

def floatNA(num):
    try:
        return float(num)
    except ValueError:
        return num

def fillMissingData(ys,samples):
    if len(ys) < samples:
        ysextra=[0]*(samples-len(ys))
        ys = ysextra + ys
    return ys


# this is the main animation function that updates the figure
rind = 1  # index for row where new data is added
def animate(i):
    global data
    global rind

    try:
        c2 = pa_q.get(False) 
        g2 = pb_q.get(False)
        s2 = c2[-1*cpudatalen:] + g2[-1*gpudatalen:] # keep only the most recent output of queues
        s2 = [floatNA(x) for x in s2]
 #       print("s2 ",s2)
      
#      if c2[0]!="#" and g2[0]!="#" and lendata == len(s2):
        data.loc[rind] = s2  # add new data to end of dataframe
        rind = rind + 1
        data = data.tail(samples) # only keep last data rows
        xs = list(range(samples)) # x ticks 
        
        for i in range(len(useheader)):
            ys = data.loc[:,useheader[i]].astype('float').tolist()
            ys = fillMissingData(ys,samples)

            axlist[i].clear()

            if useheader[i] != "CPU":
                axlist[i].bar(xs, ys, color=barcolor[i % len(barcolor)])
            else:
                # make stacked bar graph with different colors for each processor
                prevy2 = [0]*len(ys)  
                for j in range(numproc):
                    ys2 = data.iloc[:,2+j].astype('float').tolist()
                    ys2 = fillMissingData(ys2,samples)
                    axlist[i].bar(xs, ys2,bottom=prevy2) #, color=barcolor[j % len(barcolor)])
                    prevy2 = [sum(x) for x in zip(ys2,prevy2)]
            
            axlist[i].set_xticklabels([])
            axlist[i].tick_params(labelsize="x-small")
            axlist[i].text(1.005,0.5,useheader[i], horizontalalignment='left', verticalalignment='center', transform=axlist[i].transAxes)
            top = (math.floor(max(ys)/100)+1)*100
            if top < 100:
                top = 100
            if useheader[i]=="CPU":
                top = 400
            axlist[i].grid(True)
            axlist[i].set_ylim(ymin=-0.1,ymax=top)
            axlist[i].set_yticks(np.arange(top/4,top+5,top/4))
    except queue.Empty:
        pass
    
# Set up plot to call animate() function periodically
ani = animation.FuncAnimation(fig, animate,interval=1000*interval)
plt.draw()
plt.show()
