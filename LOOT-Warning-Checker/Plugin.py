"""
Plugin
======

The LOOT Warning Checker plugin.

Copyright (C) 2021 Jonathan Feenstra

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import os
from typing import Dict, List, Optional

import mobase
from PyQt5.QtCore import qCritical, qDebug, qInfo
from PyQt5.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from .Games import SUPPORTED_GAMES
from .tools.LOOT import DirtyPluginWarning, LOOTMasterlistLoader, LOOTWarning, downloadMasterlist, findMasterlistDir
from .tools.xEdit import get_xEditPathFromRegistry, scan_xEditDirectoryForExecutable, xEditGame


class LOOTWarningChecker(mobase.IPluginDiagnose):

    __warnings: Dict[int, LOOTWarning] = {}
    __lootLoader: Optional[LOOTMasterlistLoader] = None

    def __init__(self) -> None:
        super().__init__()
        self.__parentWidget: Optional[QMainWindow] = None

    def init(self, organizer: mobase.IOrganizer) -> bool:
        self.__organizer = organizer
        if not self.__organizer.onUserInterfaceInitialized(self.__onUserInterfaceInitialized):
            qCritical(self.__tr("Failed to register onUserInterfaceInitialized callback."))
            return False
        return True

    def name(self) -> str:
        return "LOOT Warning Checker"

    def author(self) -> str:
        return "Jonathan Feenstra"

    def description(self) -> str:
        return self.__tr("Checks for LOOT warnings.")

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(1, 1, 4, mobase.ReleaseType.BETA)

    def requirements(self) -> List[mobase.IPluginRequirement]:
        return [
            mobase.PluginRequirementFactory.gameDependency(games=list(SUPPORTED_GAMES.keys())),
        ]

    def settings(self) -> List[mobase.PluginSetting]:
        return [
            mobase.PluginSetting(
                "auto-update-masterlist",
                self.__tr("Automatically update the LOOT masterlist on launch"),
                False,
            ),
            mobase.PluginSetting(
                "include-info-messages",
                self.__tr("Include non-warning info messages from LOOT"),
                True,
            ),
            mobase.PluginSetting(
                "xedit-directory",
                self.__tr("Folder where the xEdit executables are located"),
                "",
            ),
        ]

    def activeProblems(self) -> List[int]:
        if self.__lootLoader is None:
            return []
        self.__warnings = dict(
            enumerate(
                self.__lootLoader.getWarnings(bool(self.__organizer.pluginSetting(self.name(), "include-info-messages")))
            )
        )

        return list(self.__warnings.keys())

    def fullDescription(self, key: int) -> str:
        return self.__warnings[key].fullDescription

    def shortDescription(self, key: int) -> str:
        return self.__warnings[key].shortDescription

    def hasGuidedFix(self, key: int) -> bool:
        warning = self.__warnings[key]
        return isinstance(warning, DirtyPluginWarning) and not warning.requiresManualFix

    def startGuidedFix(self, key: int) -> None:
        warning = self.__warnings[key]
        if isinstance(warning, DirtyPluginWarning):
            self.__quickAutoCleanPlugin(warning.pluginName)
        # TODO: Implement more guided fixes

    def __tr(self, txt: str) -> str:
        return QApplication.translate("DirtyPluginChecker", txt)

    def __onUserInterfaceInitialized(self, mainWindow: QMainWindow) -> None:
        self.__parentWidget = mainWindow
        # Update LOOT masterlist if enabled
        game = SUPPORTED_GAMES.get(self.__organizer.managedGame().gameName(), None)
        if game is not None:
            if self.__organizer.pluginSetting(self.name(), "auto-update-masterlist"):
                repoName, gameFolder = game.lootGame
                qInfo(self.__tr("Updating LOOT masterlist..."))
                try:
                    downloadMasterlist(repoName, findMasterlistDir(gameFolder))
                except OSError as exc:
                    qCritical(str(exc))
                else:
                    qInfo(self.__tr("Successfully updated LOOT masterlist."))
            try:
                self.__lootLoader = LOOTMasterlistLoader(self.__organizer, game.lootGame)
            except OSError as exc:
                qCritical(str(exc))

    def __quickAutoCleanPlugin(self, pluginName: str) -> None:
        """Use xEdit's Quick Auto Clean mode to clean the plugin.

        Args:
            pluginName (str): The name of the plugin to clean.
        """
        game = SUPPORTED_GAMES[self.__organizer.managedGame().gameName()].xEditGame
        xEditPath = self.__resolve_xEditExecutablePath(game)
        if xEditPath is not None:
            args = ["-qac", "-autoexit", "-autoload", f'"{pluginName}"']
            if not xEditPath.endswith(f"{game.specificPrefix}Edit.exe"):
                args.append(f"-{game.specificPrefix.lower()}")
            self.__organizer.startApplication(xEditPath, args=args)
            self.__organizer.refresh()
        # if executable is None, xEdit was not found and user canceled prompt

    def __resolve_xEditExecutablePath(self, game: xEditGame) -> Optional[str]:
        """Resolve the xEdit executable path.

        Args:
            game (xEditGame): The game to resolve the path for.

        Returns:
            Optional[str]: The path to the xEdit executable or None if not found.
        """
        if xEditDir := self.__organizer.pluginSetting(self.name(), "xedit-directory"):
            try:
                path = scan_xEditDirectoryForExecutable(xEditDir, game)
            except FileNotFoundError:
                qDebug(f"Invalid xEdit directory found in settings: {xEditDir}")
                path = None
            if path is not None:
                return path

        # xEdit directory setting is invalid and needs to be (re)set
        qDebug("Looking for xEdit path in registry...")
        try:
            path = get_xEditPathFromRegistry(game.specificPrefix)
            qDebug(f"Found xEdit path in registry: {path}")
        except OSError:
            path = None
            qDebug("Could not find xEdit executable in registry.")

        if path is None or not os.path.isfile(path):
            path = self.__start_xEditDirectorySelectionDialog(game)

        if path is not None and os.path.isfile(path):
            self.__organizer.setPluginSetting(self.name(), "xedit-directory", os.path.dirname(path))
        return path

    def __start_xEditDirectorySelectionDialog(self, game: xEditGame) -> Optional[str]:
        """Start the xEdit directory selection dialog.

        Args:
            game (xEditGame): The game to select the xEdit directory for.

        Returns:
            Optional[str]: The path to the xEdit executable, or None if the user canceled.
        """
        result = QMessageBox.question(
            self.__parentWidget,
            self.__tr("xEdit not detected"),
            self.__tr(
                "xEdit could not be detected automatically. Would you like to select it manually?"
                "<br/>If xEdit is not installed, you can download it from "
                '<a href="https://github.com/TES5Edit/TES5Edit/releases/latest">here</a>.'
            ),
        )
        if result != QMessageBox.Yes:
            return None

        path = None
        while path is None or not os.path.isfile(path):
            try:
                path = self.__promptUserFor_xEditLocation(game)
            except FileNotFoundError:
                result = QMessageBox.question(
                    self.__parentWidget,
                    self.__tr("Invalid path"),
                    self.__tr("The selected path is invalid. Would you like to try another location?"),
                    QMessageBox.StandardButtons(QMessageBox.Yes | QMessageBox.No),
                )
                if result == QMessageBox.Yes:
                    continue
                return None
            if path is None:
                # User canceled the prompt
                return None
        return path

    def __promptUserFor_xEditLocation(self, game: xEditGame) -> Optional[str]:
        """
        Prompt the user to select the xEdit directory and return the file path.

        Args:
            generalPrefix (str): The general prefix of the xEdit executable.
            specificPrefix (str): The specific prefix of the xEdit executable.

        Returns:
            Optional[str]: The path to the xEdit executable, or None if the user canceled the prompt.

        Raises:
            FileNotFoundError: If the xEdit executable could not be found in the specified directory.
        """
        xEditDir = QFileDialog.getExistingDirectory(
            self.__parentWidget,
            self.__tr("Select the folder where the xEdit executable is located"),
            options=QFileDialog.ShowDirsOnly,
        )
        qDebug(f"Selected xEdit directory: {xEditDir}")
        if xEditDir != "":
            return scan_xEditDirectoryForExecutable(xEditDir, game)
