'''
Created on 01/05/2013

@author: mikel
'''
def event_is_set(event):
    #Return the event's status
    if hasattr(event, 'is_set'):
        return event.is_set()
    
    #Old Python version fallback for the above
    else:
        return event.isSet()
