'''
Created on 18/04/2011

@author: mikel
'''
import threads



def run_in_thread(func=None, threads_per_class=10, single_instance=False):
    if callable(func):
        decorator = run_in_thread()
        return decorator(func)
    
    class decorator_class(object):
        __func = None
        
        
        def __init__(self, func):
            self.__func = func
        
        
        def __call__(self, *args, **kwargs):
            tm = threads.TaskManager(threads_per_class, single_instance)
            tm.add(self.__func, *args, **kwargs)
        
        
        def __get__(self, obj, type=None):
            return self.__class__(self.__func.__get__(obj, type))
    
    return decorator_class
