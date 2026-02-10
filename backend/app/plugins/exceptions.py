class PluginError(Exception): pass
class PluginImportError(PluginError, ImportError): pass
class PluginPathInvalidError(PluginImportError): pass
class PluginFinderNotInstalledError(PluginImportError): pass
