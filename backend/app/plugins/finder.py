from typing import Iterable, Sequence, Generator
from types import ModuleType
import importlib
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec, SOURCE_SUFFIXES
import sys

from ._types import PluginSource, AnyPluginSource, PluginParts, PluginPathInfo, PluginParts
from ._loader import PluginLoader
from .exceptions import PluginPathInvalidError, PluginFinderNotInstalledError

__all__ = [
    "PluginFinder",
]

# NOTE: Angle brackets intentionally prevent accidental real imports.
VIRTUAL_BASE_PACKAGE = __package__ or "<plugins>"


# ==============================================================================
# PluginFinder

class PluginFinder(MetaPathFinder):
    """
    A MetaPathFinder for plugins.
    """
    name: str
    sources: tuple[PluginSource, ...]
    exts: tuple[str, ...]

    _plugin_file_cache: dict[PluginParts, PluginPathInfo | None]
    _plugin_folder_cache: dict[PluginParts, tuple[PluginPathInfo, ...]]

    def __init__(
        self,
        name: str,
        sources: Iterable[AnyPluginSource],
        exts: Iterable[str] = SOURCE_SUFFIXES
    ):
        PluginParts.validate_part(name)

        self.name = name
        self.sources = tuple(PluginSource(x) for x in sources)
        self.exts = tuple(exts)

        self._plugin_file_cache = {}
        self._plugin_folder_cache = {}

    @property
    def package(self) -> str:
        """Return the plugin package name."""
        # NOTE: Angle brackets intentionally prevent accidental
        #       imports from other (plugin) packages.
        return f"{VIRTUAL_BASE_PACKAGE}.<{self.name}>"

    # def _is_sub_package(self, fullname: str) -> bool:
    #     """Return True if fullname is a sub-package of this package."""
    #     package = self.package
    #     return fullname.startswith(f"{package}.") or fullname == package

    def _get_plugin_parts(self, module_fullname: str) -> PluginParts:
        """
        Return the plugin parts for the given module fullname.
        Raise ValueError if it is not a sub-package of this package.
        """
        package = self.package
        if module_fullname == package:
            return PluginParts()

        base = f"{package}."
        if not module_fullname.startswith(base):
            raise ValueError(f"{module_fullname} is not a sub-package of {package}")

        plugin_path = module_fullname[len(base):]
        return PluginParts.from_plugin_path(plugin_path)

    def is_installed(self) -> bool:
        """Return True if plugin finder is installed in sys.meta_path."""
        return self in sys.meta_path

    def install(self) -> None:
        """Append plugin finder to sys.meta_path."""
        if self.is_installed():
            return

        sys.meta_path.append(self)

        # Clear any loaders that might already be in use by the FileFinder
        sys.path_importer_cache.clear()
        self.invalidate_caches()

    def invalidate_caches(self) -> None:
        """Clear all internal caches."""
        self._plugin_file_cache.clear()
        self._plugin_folder_cache.clear()

    def _find_plugin_info(self, parts: PluginParts) -> PluginPathInfo | None:
        """
        Find PluginPathInfo for given `parts`.
        Raise ValueError if `parts` is invalid.
        """
        try:
            return self._plugin_file_cache[parts]
        except KeyError:
            pass

        parts.validate()
        plugin_path = PluginSource(*parts)

        for source in self.sources:
            full_path = source / plugin_path

            if full_path.is_dir():
                info = PluginPathInfo(parts, True, full_path)
                self._plugin_file_cache[parts] = info
                return info

            for ext in self.exts:
                file = full_path.with_name(full_path.name + ext)
                if file.is_file():
                    info = PluginPathInfo(parts, False, file)
                    self._plugin_file_cache[parts] = info
                    return info

        self._plugin_file_cache[parts] = None
        return None

    def _iter_sub_plugin_info(self, parts: PluginParts) -> Generator[PluginPathInfo, None, None]:
        """
        Generate PluginPathInfo for all sub-plugins of given `parts`.
        Raise ValueError if `parts` is invalid.
        """
        cache: Sequence[PluginPathInfo]
        try:
            cache = self._plugin_folder_cache[parts]
        except KeyError:
            pass
        else:
            yield from cache
            return

        parts.validate()
        plugin_path = PluginSource(*parts)

        cache = []
        yielded: set[str] = set()
        for source in self.sources:
            full_path = source / plugin_path
            if not full_path.is_dir():
                continue

            for file in full_path.iterdir():
                stem = file.stem
                if stem in yielded:
                    continue

                if not file.exists():
                    continue

                ispkg = file.is_dir()
                if ispkg:
                    if file.suffix:
                        continue
                else:
                    if file.suffix not in self.exts:
                        continue

                try:
                    PluginParts.validate_part(stem)
                except ValueError:
                    continue

                info = PluginPathInfo(parts.appended(stem), ispkg, file)
                self._plugin_file_cache[info.parts] = info
                cache.append(info)
                yielded.add(stem)
                yield info

        self._plugin_folder_cache[parts] = tuple(cache)

    def iter_plugins(self, plugin_path: str | None = None) -> Generator[tuple[str, bool], None, None]:
        """Return a generator of [plugin_path, is_package] pairs for all plugins in given `plugin_path`."""
        parts = PluginParts.from_plugin_path(plugin_path)
        for info in self._iter_sub_plugin_info(parts):
            yield info.plugin_path, info.ispkg

    def import_plugin(self, plugin_path: str) -> ModuleType:
        """
        Import a plugin.
        Raise PluginFinderNotInstalledError if plugin finder is not installed.
        Raise PluginPathInvalidError if `plugin_path` is invalid.
        """
        if not self.is_installed():
            raise PluginFinderNotInstalledError(
                "The Plugin-Finder must be installed before importing plugins."
            )

        try:
            parts = PluginParts.from_plugin_path(plugin_path)
            parts.validate()
        except ValueError as e:
            raise PluginPathInvalidError(
                f"Invalid plugin path {plugin_path!r}: {e}"
            ) from e

        return importlib.import_module(f"{self.package}.{parts}")

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname == VIRTUAL_BASE_PACKAGE:
            return ModuleSpec(fullname, None, is_package=True)
        if fullname == self.package:
            return ModuleSpec(fullname, None, is_package=True)

        try:
            parts = self._get_plugin_parts(fullname)
            info = self._find_plugin_info(parts)
        except ValueError:
            return None

        if info is None:
            return None

        if info.ispkg:
            return ModuleSpec(fullname, None, is_package=True)

        file = info.file
        loader = PluginLoader(fullname, file)

        spec = ModuleSpec(fullname, loader, origin=file)
        spec.submodule_search_locations = []
        spec.has_location = True
        return spec
