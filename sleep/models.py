from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import localtime

import pytz
import datetime
import math

class SleepManager(models.Manager):
    def totalSleep(self):
        sleeps =  Sleep.objects.all()
        return sum((sleep.end_time - sleep.start_time for sleep in sleeps),datetime.timedelta(0))

    def sleepTimes(self,res=1):
        sleeps = Sleep.objects.all()
        atTime = [0] * (24 * 60 / res) 
        for sleep in sleeps:
            startDate = localtime(sleep.start_time).date()
            endDate = localtime(sleep.end_time).date()
            dr = [startDate + datetime.timedelta(i) for i in range((endDate-startDate).days + 1)]
            for d in dr:
                if d == startDate:
                    startTime = localtime(sleep.start_time).time()
                else:
                    startTime = datetime.time(0)
                if d == endDate:
                    endTime = localtime(sleep.end_time).time()
                else:
                    endTime = datetime.time(23,59)
                for i in range((startTime.hour * 60 + startTime.minute) / res, (endTime.hour * 60 + endTime.minute + 1) / res):
                    atTime[i]+=1
        return atTime

    def sleepStartEndTimes(self,res=10):
        sleeps = Sleep.objects.all()
        startAtTime = [0] * (24 * 60 / res)
        endAtTime = [0] * (24 * 60 / res)
        for sleep in sleeps:
            startTime = localtime(sleep.start_time).time()
            endTime = localtime(sleep.end_time).time()
            startAtTime[(startTime.hour * 60 + startTime.minute) / res]+=1
            endAtTime[(endTime.hour * 60 + endTime.minute) / res]+=1
        return (startAtTime,endAtTime)

    def sleepLengths(self,res=10):
        sleeps = Sleep.objects.all()
        lengths = map(lambda x: x.length().total_seconds() / (60*res),sleeps)
        packed = [0] * int(max(lengths)+1)
        for length in lengths:
            if length>0:
                packed[int(length)]+=1
        return packed


class Sleep(models.Model):
    objects = SleepManager()

    user = models.ForeignKey(User)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    comments = models.TextField(blank=True)
    date = models.DateField()

    def __unicode__(self):
        return "Sleep from %s to %s" % (self.start_time,self.end_time)

    def length(self):
        return self.end_time - self.start_time

    def overlaps(self, otherSleep):
        return (min(self.end_time, otherSleep.end_time) - max(self.start_time, otherSleep.start_time) > datetime.timedelta(0))

    def validate_unique(self, exclude=None):
        #Yes this is derpy and inefficient and really should actually use the exclude field
        from django.core.exceptions import ValidationError, NON_FIELD_ERRORS
        sleepq = self.user.sleep_set.all().exclude(pk = self.pk)
        for i in sleepq:
            if self.overlaps(i):
                raise ValidationError

class Allnighter(models.Model):
    user = models.ForeignKey(User)
    date = models.DateField()
    comments = models.TextField(blank=True)

class SleeperProfile(models.Model):
    user = models.OneToOneField(User)
    # all other fields should have a default
    PRIVACY_HIDDEN = -100
    PRIVACY_REDACTED = -50
    PRIVACY_NORMAL = 0
    PRIVACY_STATS = 50
    PRIVACY_PUBLIC = 100
    PRIVACY_CHOICES = (
            (PRIVACY_HIDDEN, 'Hidden'),
            (PRIVACY_REDACTED, 'Redacted'),
            (PRIVACY_NORMAL, 'Normal'),
            (PRIVACY_STATS, 'Stats Public'),
            (PRIVACY_PUBLIC, 'Sleep Public'),
            )
    privacy = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL,verbose_name='Privacy to anonymous users')
    privacyLoggedIn = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL,verbose_name='Privacy to logged-in users')
    privacyFriends = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL,verbose_name='Privacy to friends')
    friends = models.ManyToManyField(User,related_name='friends+',blank=True)
    follows = models.ManyToManyField(User,related_name='follows+',blank=True)
    requested = models.ManyToManyField(User,related_name='requests',blank=True,through='FriendRequest')
    use12HourTime = models.BooleanField(default=False)

    emailreminders = models.BooleanField(default=False)

    timezone = models.CharField(max_length=255, choices = [ (i,i) for i in pytz.common_timezones], default="US/Eastern")

    idealSleep = models.DecimalField(max_digits=4, decimal_places=2, default = 7.5)

    def getIdealSleep(self):
        """Returns idealSleep as a timedelta"""
        return datetime.timedelta(hours=float(self.idealSleep))

    def __unicode__(self):
        return "SleeperProfile for user %s" % self.user

class SleeperManager(models.Manager):
    def sorted_sleepers(self,sortBy='zScore',user=None):
        sleepers = Sleeper.objects.all().prefetch_related('sleep_set','sleeperprofile')
        scored=[]
        extra=[]
        for sleeper in sleepers:
            if len(sleeper.sleepPerDay())>2 and sleeper.sleepPerDay(packDates=True)[-1]['date'] >= datetime.date.today()-datetime.timedelta(5):
                p = sleeper.getOrCreateProfile()
                if user is None:
                    priv = p.PRIVACY_HIDDEN
                elif user is 'all':
                    priv = p.PRIVACY_PUBLIC
                elif user.is_anonymous():
                    priv = p.privacy
                elif user.pk==sleeper.pk:
                    priv = p.PRIVACY_PUBLIC
                else:
                    priv = p.privacyLoggedIn

                if priv<=p.PRIVACY_REDACTED:
                    sleeper.displayName="[redacted]"
                else:
                    sleeper.displayName=sleeper.username
                if priv>p.PRIVACY_HIDDEN:
                    d=sleeper.decayStats()
                    d['user']=sleeper
                    if 'is_authenticated' in dir(user) and user.is_authenticated():
                        if user.pk==sleeper.pk:
                            d['opcode']='me' #I'm using opcodes to mark specific users as self or friend.
                    else:
                        d['opcode'] = None
                    scored.append(d)
            else:
                if 'is_authenticated' in dir(user) and user.is_authenticated() and user.pk == sleeper.pk:
                    d = sleeper.decayStats()
                    d['rank']='n/a'
                    sleeper.displayName=sleeper.username
                    d['user']=sleeper
                    d['opcode']='me'
                    extra.append(d)
        if sortBy in ['stDev']:
            scored.sort(key=lambda x: x[sortBy])
        else:
            scored.sort(key=lambda x: -x[sortBy])
        for i in xrange(len(scored)):
            scored[i]['rank']=i+1
        return scored+extra

    def bestByTime(self,start=datetime.datetime.min,end=datetime.datetime.max,user=None):
        sleepers = Sleeper.objects.all().prefetch_related('sleep_set','sleeperprofile')
        scored=[]
        for sleeper in sleepers:
            p = sleeper.getOrCreateProfile()
            if user is None:
                priv = p.PRIVACY_HIDDEN
            elif user is 'all':
                priv = p.PRIVACY_PUBLIC
            elif user.is_anonymous():
                priv = p.privacy
            elif user.pk==sleeper.pk:
                priv = p.PRIVACY_PUBLIC
            else:
                priv = p.privacyLoggedIn

            if priv<=p.PRIVACY_REDACTED:
                sleeper.displayName="[redacted]"
            else:
                sleeper.displayName=sleeper.username
            if priv>p.PRIVACY_HIDDEN:
                d={'time':sleeper.timeSleptByTime(start,end)}
                d['user']=sleeper
                if 'is_authenticated' in dir(user) and user.is_authenticated():
                    if user.pk==sleeper.pk:
                        d['opcode']='me' #I'm using opcodes to mark specific users as self or friend.
                else:
                    d['opcode'] = None
                scored.append(d)
        scored.sort(key=lambda x: -x['time'])
        for i in xrange(len(scored)):
            scored[i]['rank']=i+1
        return scored

class FriendRequest(models.Model):
    requestor = models.ForeignKey(SleeperProfile)
    requestee = models.ForeignKey(User)
    accepted = models.NullBooleanField()
        

class Sleeper(User):
    class Meta:
        proxy = True

    objects = SleeperManager()

    def getOrCreateProfile(self):
        return SleeperProfile.objects.get_or_create(user=self)[0]

    def timeSleptByDate(self,start=datetime.date.min,end=datetime.date.max):
        sleeps = self.sleep_set.filter(date__gte=start,date__lte=end)
        return sum([s.end_time-s.start_time for s in sleeps],datetime.timedelta(0))

    def timeSleptByTime(self,start=datetime.datetime.min,end=datetime.datetime.max):
        sleeps = self.sleep_set.filter(end_time__gt=start,start_time__lt=end)
        return sum([min(s.end_time,end)-max(s.start_time,start) for s in sleeps],datetime.timedelta(0))

    def sleepPerDay(self,start=datetime.date.min,end=datetime.date.max,packDates=False,hours=False):
        if start==datetime.date.min and end==datetime.date.max:
            sleeps = self.sleep_set.values('date','start_time','end_time')
        else:
            sleeps = self.sleep_set.filter(date__gte=start,date__lte=end).values('date','start_time','end_time')
        if sleeps:
            dates=map(lambda x: x['date'], sleeps)
            first = min(dates)
            last = max(dates)
            n = (last-first).days + 1
            dateRange = [first + datetime.timedelta(i) for i in range(0,n)]
            byDays = [sum([(s['end_time']-s['start_time']).total_seconds() for s in filter(lambda x: x['date']==d,sleeps)]) for d in dateRange]
            if hours:
                byDays = map(lambda x: x/3600,byDays)
            if packDates:
                return [{'date' : first + datetime.timedelta(i), 'slept' : byDays[i]} for i in range(0,n)]
            else:
                return byDays
        else:
            return []

    def goToSleepTime(self, date=datetime.date.today()):
        sleeps = self.sleep_set.filter(date=date)
        if sleeps.count() == 0: return None
        times = [s.start_time for s in sleeps if s.length() >= datetime.timedelta(hours=3)]
        if len(times) == 0: return None
        else: return max(times).time()

    def avgGoToSleepTime(self, start = datetime.date.min, end=datetime.date.max):
        import math
        sleeps = self.sleep_set.filter(date__gte=start, date__lte=end).values('date', 'start_time', 'end_time')
        if sleeps: dates=map(lambda x: x['date'], sleeps)
        else: return None
        def genDays(start, end):
            d = start
            while d <= end:
                yield d
                d += datetime.timedelta(1)
        times = [self.goToSleepTime(d) for d in genDays(min(dates), max(dates))]
        ctimes = [t.hour*3600 + t.minute*60 + t.second for t in times if t != None]
        if len(ctimes) == 0: return None
        av = sum(ctimes)/len(ctimes)
        return datetime.time(int(math.floor(av/3600)), int(math.floor((av%3600)/60)), int(math.floor((av%60))))

    def wakeUpTime(self, date=datetime.date.today()):
        sleeps = self.sleep_set.filter(date=date)
        if sleeps.count() == 0: return None
        times = [s.end_time for s in sleeps if s.length() >= datetime.timedelta(hours=3)]
        if len(times) == 0: return None
        else: return min(times).time()

    def avgWakeUpTime(self, start = datetime.date.min, end=datetime.date.max):
        import math
        sleeps = self.sleep_set.filter(date__gte=start, date__lte=end).values('date', 'start_time', 'end_time')
        if sleeps: dates=map(lambda x: x['date'], sleeps)
        else: return None
        def genDays(start, end):
            d = start
            while d <= end:
                yield d
                d += datetime.timedelta(1)
        times = [self.wakeUpTime(d) for d in genDays(min(dates), max(dates))]
        ctimes = [t.hour*3600 + t.minute*60 + t.second for t in times if t != None]
        if len(ctimes) == 0: return None
        av = sum(ctimes)/len(ctimes)
        return datetime.time(int(math.floor(av/3600)), int(math.floor((av%3600)/60)), int(math.floor((av%60))))

    def movingStats(self,start=datetime.date.min,end=datetime.date.max):
        sleep = self.sleepPerDay(start,end)
        d = {}
        try:
            avg = sum(sleep)/len(sleep)
            d['avg']=avg
            if len(sleep)>2:
                stDev = math.sqrt(sum(map(lambda x: (x-avg)**2, sleep))/(len(sleep)-1.5)) #subtracting 1.5 is correct according to wikipedia
                d['stDev']=stDev
                d['zScore']=avg-stDev
        except:
            pass
        try:
            offset = 4*60*60.
            avgRecip = 1/(sum(map(lambda x: 1/(offset+x),sleep))/len(sleep))-offset
            d['avgRecip']=avgRecip
            avgSqrt = (sum(map(lambda x: math.sqrt(x),sleep))/len(sleep))**2
            d['avgSqrt']=avgSqrt
            avgLog = math.exp(sum(map(lambda x: math.log(x+1),sleep))/len(sleep))-1
            d['avgLog']=avgLog
        except:
            pass
        for k in ['avg','stDev','zScore','avgSqrt','avgLog','avgRecip']:
            if k not in d:
                d[k]=datetime.timedelta(0)
            else:
                d[k]=datetime.timedelta(0,d[k])
        return d

    def decaying(self,data,hl,stDev=False):
        s = 0
        w = 0
        for i in range(len(data)):
            s+=2**(-i/float(hl))*data[-i-1]
            w+=2**(-i/float(hl))
        if stDev:
            w = w*(len(data)-1.5)/len(data)
        return s/w

    def decayStats(self,end=datetime.date.max,hl=4):
        sleep = self.sleepPerDay(datetime.date.min,end)
        d = {}
        try:
            avg = self.decaying(sleep,hl)
            d['avg']=avg
            stDev = math.sqrt(self.decaying(map(lambda x: (x-avg)**2,sleep),hl,True))
            d['stDev']=stDev
            d['zScore']=avg-stDev
        except:
            pass
        try:
            offset = 4*60*60.
            avgRecip = 1/(self.decaying(map(lambda x: 1/(offset+x),sleep),hl))-offset
            d['avgRecip']=avgRecip
            avgSqrt = self.decaying(map(lambda x: math.sqrt(x),sleep),hl)**2
            d['avgSqrt']=avgSqrt
            avgLog = math.exp(self.decaying(map(lambda x: math.log(x+1),sleep),hl))-1
            d['avgLog']=avgLog
        except:
            pass
        for k in ['avg','stDev','zScore','avgSqrt','avgLog','avgRecip']:
            if k not in d:
                d[k]=datetime.timedelta(0)
            else:
                d[k]=datetime.timedelta(0,d[k])
        return d

