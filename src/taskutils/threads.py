'''
Created on 22/10/2011

@author: mikel
'''
import collections
import threading



#Thread local var storage
__thread_locals = threading.local()


def current_task():
    return __thread_locals.current_task


def set_current_task(task):
    __thread_locals.current_task = task



class TaskError(Exception):
    pass



class TaskCancelledError(TaskError):
    pass



class TaskItem:
    __target = None
    __group = None
    __args = None
    __kwargs = None
    
    __wait_event = None
    __end_event = None
    
    __is_running = None
    __is_cancelled = None
    
    
    def __init__(self, target, group=None, *args, **kwargs):
        self.__target = target
        self.__group = group
        self.__args = args
        self.__kwargs = kwargs
        self.__wait_event = threading.Event()
        self.__end_event = threading.Event()
        self.__is_running = False
        self.__is_cancelled = False
    
    
    def _generate_group(self):
        if hasattr(self.__target, 'im_class'):
            path = [
                self.__target.im_class.__module__,
                self.__target.im_class.__name__,
                self.__target.__name__
            ]
            
        else:
            path = [
                self.__target.__module__,
                self.__target.__name__
            ]
        
        return '.'.join(path)
    
    
    def wait(self, timeout=None):
        self.__wait_event.wait(timeout)
        
        #If it was cancelled
        if self.__is_cancelled:
            #TODO: Report task id in exception message
            raise TaskCancelledError("Task cancelled")
    
    
    def notify(self):
        self.__wait_event.set()
        self.__wait_event.clear()
    
    
    def cancel(self):
        self.__is_cancelled = True
        self.notify_wait()
    
    
    def is_cancelled(self):
        return self.__is_cancelled
    
    
    def get_group(self):
        if self.__group is None:
            self.__group = self._generate_group()
        
        return self.__group
    
    
    def run(self):
        try:
            set_current_task(self)
            self.__is_running = True
            self.__target(*self.__args, **self.__kwargs)
        finally:
            self.__is_running = False
            self.__end_event.set()
        
    
    def is_running(self):
        return self.__is_running
        
    
    def join(self, timeout=None):
        self.__end_event.wait(timeout)
        
        #Return the event's status
        if hasattr(self.__end_event, 'is_set'):
            return self.__end_event.is_set()
        
        #Old Python version fallback for the above
        else:
            return self.__end_event.isSet()



class TaskQueueManager:
    __groups = None
    
    
    def __init__(self):
        self.__groups = {}
    
    
    def has_group(self, group):
        return group in self.__groups
    
    
    def get_tasks(self, group):
        
        #Avoid returning the live queue
        return list(self.__groups[group])
    
    
    def add(self, task):
        group = task.get_group()
        
        #New container queue needed
        if not self.has_group(group):
            self.__groups[group] = collections.deque([task])
        
        #Append task to existing queue normally
        else:
            self.__groups[group].append(task)
    
    
    def _remove(self, container, task):
        #Queue has remove()!
        if hasattr(container, 'remove'):
            container.remove(task)
        
        #pre-2.5, no remove(), snif.
        else:
            for idx, item in enumerate(container):
                if item == task:
                    del container[idx]
                    return
    
    
    def remove(self, task):
        group = task.get_group()
        
        if group not in self.__groups:
            raise KeyError('Unknown group id: %s' % group)
        
        #Remove the task first
        self._remove(self.__groups[group], task)
        
        #If queue queue reached to zero length, remove it
        if len(self.__groups[group]) == 0:
            del self.__groups[group]



class TaskCountManager:
    __groups = None
    
    
    def __init__(self):
        self.__groups = {}
    
    
    def can_run(self, task, max_concurrency):
        if max_concurrency == 0:
            return True
        
        elif task.get_group() not in self.__groups:
            return True
        
        elif len(self.__groups[task.get_group()]) < max_concurrency:
            return True
        
        else:
            return False
    
    
    def add_task(self, task):
        if task.get_group() not in self.__groups:
            self.__groups[task.get_group()] = [task]
        
        else:
            self.__groups[task.get_group()].append(task)
    
    
    def get_tasks(self, group):
        return list(self.__groups[group])
    
    
    def remove_task(self, task):
        if task.get_group() not in self.__groups:
            raise KeyError('Unknown group id: %s' % task.get_group())
        
        elif len(self.__groups[task.get_group()]) == 1:
            del self.__groups[task.get_group()]
        
        else:
            self.__groups[task.get_group()].remove(task)



class TaskManager:
    #Static class instances
    __queue_manager = TaskQueueManager()
    __count_manager = TaskCountManager()
    __lock = threading.RLock()
    
    
    def _get_next_task(self, group, max_concurrency):
        for task in self.__queue_manager.get_tasks(group):
            if self.__count_manager.can_run(task, max_concurrency):
                return task
        
        return None
    
    
    def _task_post(self, task, max_concurrency):
        self.__lock.acquire()
        
        try:
            #Decrement task count
            self.__count_manager.remove_task(task)
            
            #A shortcut to the task's group
            group = task.get_group()
            
            #Handle enqueued tasks
            if self.__queue_manager.has_group(group):
                #Get the next runnable task on the container
                next_task = self._get_next_task(group, max_concurrency)
                
                #If it got started remove it from the queue
                if next_task is not None:
                    
                    
                    if self._try_start(next_task, max_concurrency):
                        self.__queue_manager.remove(next_task)
        
        finally:
            self.__lock.release()
    
    
    def _try_start(self, task, max_concurrency):
        def runner():
            #Run the actual task
            task.run()
            
            #And execute post actions
            self._task_post(task, max_concurrency)
        
        #Try running the task
        if self.__count_manager.can_run(task, max_concurrency):
            
            #Register that task
            self.__count_manager.add_task(task)
            
            #And start it in a thread
            thread = threading.Thread(target=runner)
            thread.start()
            
            return True
        
        else:
            return False
    
    
    def add(self, target, group=None, max_concurrency=0, *args, **kwargs):
        task = TaskItem(target, group, *args, **kwargs)
        self.__lock.acquire()
        
        try:
            #Enqueue if we can't start it
            if not self._try_start(task, max_concurrency):
                self.__queue_manager.add(task)
        
        finally:
            self.__lock.release()
        
        return task