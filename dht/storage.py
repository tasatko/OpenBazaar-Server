import time

from collections import OrderedDict
from collections import MutableMapping

from zope.interface import implements
from zope.interface import Interface

from kprotocol import Value

from threading import RLock


class IStorage(Interface):
    """
    Local storage for this node.
    """

    def __setitem__(key, value):
        """
        Set a key to the given value.
        """

    def __getitem__(key):
        """
        Get the given key.  If item doesn't exist, raises C{KeyError}
        """

    def get(key, default=None):
        """
        Get given key.  If not found, return default.
        """

    def cull():
        """
        Iterate over all keys and remove expired items
        """

    def iterkeys():
        """
        Get the key iterator for this storage, should yield a list of keys
        """

    def iteritems(keyword):
        """
        Get the value iterator for the given keyword, should yield a tuple of (key, value)
        """


class ForgetfulStorage(object):
    implements(IStorage)

    def __init__(self, ttl=604800):
        """
        By default, max age is a week.
        """
        self.data = OrderedDict()
        self.ttl = ttl

    def __setitem__(self, keyword, values):
        valueDic = TTLDict(self.ttl)
        if keyword in self.data:
            valueDic = self.data[keyword]
            if values[0] not in valueDic:
                valueDic[values[0]] = values[1]
            elif valueDic[values[0]] == values[1]:
                valueDic.set_ttl(values[0], self.ttl)
        else:
            valueDic[values[0]] = values[1]
            self.data[keyword] = valueDic
        self.cull()

    def cull(self):
        for key in self.data.iterkeys():
            self.data[key].cull()
            if len(self.data[key]) == 0:
                del self.data[key]

    def get(self, keyword, default=None):
        self.cull()
        if keyword in self.data:
            ret = []
            for k, v in self[keyword].items():
                value = Value()
                value.contractID = k
                value.serializedNode = v
                ret.append(value.SerializeToString())
            return ret
        return default

    def __getitem__(self, keyword):
        self.cull()
        return self.data[keyword]

    def __iter__(self):
        self.cull()
        return iter(self.data)

    def __repr__(self):
        self.cull()
        return repr(self.data)

    def iterkeys(self):
        self.cull()
        return self.data.iterkeys()

    def iteritems(self, keyword):
        self.cull()
        return self.data[keyword].iteritems()

class TTLDict(MutableMapping):
    """
    Dictionary with TTL
    Extra args and kwargs are passed to initial .update() call
    """
    def __init__(self, default_ttl, *args, **kwargs):
        self._default_ttl = default_ttl
        self._values = {}
        self._lock = RLock()
        self.update(*args, **kwargs)

    def __repr__(self):
        return '<TTLDict@%#08x; ttl=%r, v=%r;>' % (id(self), self._default_ttl, self._values)

    def set_ttl(self, key, ttl, now=None):
        """ Set TTL for the given key """
        if now is None:
            now = time.time()
        with self._lock:
            _expire, value = self._values[key]
            self._values[key] = (now + ttl, value)

    def get_ttl(self, key, now=None):
        """ Return remaining TTL for a key """
        if now is None:
            now = time.time()
        with self._lock:
            expire, _value = self._values[key]
            return expire - now

    def expire_at(self, key, timestamp):
        """ Set the key expire timestamp """
        with self._lock:
            _expire, value = self._values[key]
            self._values[key] = (timestamp, value)

    def is_expired(self, key, now=None, remove=False):
        """ Check if key has expired """
        with self._lock:
            if now is None:
                now = time.time()
            expire, _value = self._values[key]
            if expire is None:
                return False
            expired = expire < now
            if expired and remove:
                self.__delitem__(key)
            return expired

    def __len__(self):
        with self._lock:
            for key in self._values.keys():
                self.is_expired(key, remove=True)
            return len(self._values)

    def __iter__(self):
        with self._lock:
            for key in self._values.keys():
                if not self.is_expired(key, remove=True):
                    yield key

    def __setitem__(self, key, value):
        with self._lock:
            if self._default_ttl is None:
                expire = None
            else:
                expire = time.time() + self._default_ttl
            self._values[key] = (expire, value)

    def __delitem__(self, key):
        with self._lock:
            del self._values[key]

    def __getitem__(self, key):
        with self._lock:
            self.is_expired(key, remove=True)
            return self._values[key][1]

    def cull(self):
        with self._lock:
            for key in self._values.keys():
                self.is_expired(key, remove=True)