{-| Implementation of the generic daemon functionality.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.Daemon
  ( DaemonOptions(..)
  , OptType
  , defaultOptions
  , oShowHelp
  , oShowVer
  , oNoDaemonize
  , oNoUserChecks
  , oDebug
  , oPort
  , parseArgs
  , writePidFile
  , genericMain
  ) where

import Control.Monad
import qualified Data.Version
import Data.Word
import System.Console.GetOpt
import System.Exit
import System.Environment
import System.Info
import System.IO
import System.Posix.Directory
import System.Posix.Files
import System.Posix.IO
import System.Posix.Process
import System.Posix.Types
import Text.Printf

import Ganeti.Logging
import Ganeti.Runtime
import Ganeti.BasicTypes
import Ganeti.HTools.Utils
import qualified Ganeti.HTools.Version as Version(version)
import qualified Ganeti.Constants as C

-- * Data types

-- | Command line options structure.
data DaemonOptions = DaemonOptions
  { optShowHelp     :: Bool           -- ^ Just show the help
  , optShowVer      :: Bool           -- ^ Just show the program version
  , optDaemonize    :: Bool           -- ^ Whether to daemonize or not
  , optPort         :: Maybe Word16   -- ^ Override for the network port
  , optDebug        :: Bool           -- ^ Enable debug messages
  , optNoUserChecks :: Bool           -- ^ Ignore user checks
  }

-- | Default values for the command line options.
defaultOptions :: DaemonOptions
defaultOptions  = DaemonOptions
  { optShowHelp     = False
  , optShowVer      = False
  , optDaemonize    = True
  , optPort         = Nothing
  , optDebug        = False
  , optNoUserChecks = False
  }

-- | Abrreviation for the option type.
type OptType = OptDescr (DaemonOptions -> Result DaemonOptions)

-- | Helper function for required arguments which need to be converted
-- as opposed to stored just as string.
reqWithConversion :: (String -> Result a)
                  -> (a -> DaemonOptions -> Result DaemonOptions)
                  -> String
                  -> ArgDescr (DaemonOptions -> Result DaemonOptions)
reqWithConversion conversion_fn updater_fn metavar =
  ReqArg (\string_opt opts -> do
            parsed_value <- conversion_fn string_opt
            updater_fn parsed_value opts) metavar

-- * Command line options

oShowHelp :: OptType
oShowHelp = Option "h" ["help"]
            (NoArg (\ opts -> Ok opts { optShowHelp = True}))
            "Show the help message and exit"

oShowVer :: OptType
oShowVer = Option "V" ["version"]
           (NoArg (\ opts -> Ok opts { optShowVer = True}))
           "Show the version of the program and exit"

oNoDaemonize :: OptType
oNoDaemonize = Option "f" ["foreground"]
               (NoArg (\ opts -> Ok opts { optDaemonize = False}))
               "Don't detach from the current terminal"

oDebug :: OptType
oDebug = Option "d" ["debug"]
         (NoArg (\ opts -> Ok opts { optDebug = True }))
         "Enable debug messages"

oNoUserChecks :: OptType
oNoUserChecks = Option "" ["no-user-checks"]
         (NoArg (\ opts -> Ok opts { optNoUserChecks = True }))
         "Ignore user checks"

oPort :: Int -> OptType
oPort def = Option "p" ["port"]
            (reqWithConversion (tryRead "reading port")
             (\port opts -> Ok opts { optPort = Just port }) "PORT")
            ("Network port (default: " ++ show def ++ ")")

-- | Usage info.
usageHelp :: String -> [OptType] -> String
usageHelp progname =
  usageInfo (printf "%s %s\nUsage: %s [OPTION...]"
             progname Version.version progname)

-- | Command line parser, using the 'Options' structure.
parseOpts :: [String]               -- ^ The command line arguments
          -> String                 -- ^ The program name
          -> [OptType]              -- ^ The supported command line options
          -> IO (DaemonOptions, [String]) -- ^ The resulting options
                                          -- and leftover arguments
parseOpts argv progname options =
  case getOpt Permute options argv of
    (opt_list, args, []) ->
      do
        parsed_opts <-
          case foldM (flip id) defaultOptions opt_list of
            Bad msg -> do
              hPutStrLn stderr "Error while parsing command\
                               \line arguments:"
              hPutStrLn stderr msg
              exitWith $ ExitFailure 1
            Ok val -> return val
        return (parsed_opts, args)
    (_, _, errs) -> do
      hPutStrLn stderr $ "Command line error: "  ++ concat errs
      hPutStrLn stderr $ usageHelp progname options
      exitWith $ ExitFailure 2

-- | Small wrapper over getArgs and 'parseOpts'.
parseArgs :: String -> [OptType] -> IO (DaemonOptions, [String])
parseArgs cmd options = do
  cmd_args <- getArgs
  parseOpts cmd_args cmd options

-- * Daemon-related functions
-- | PID file mode.
pidFileMode :: FileMode
pidFileMode = unionFileModes ownerReadMode ownerWriteMode

-- | Writes a PID file and locks it.
_writePidFile :: FilePath -> IO Fd
_writePidFile path = do
  fd <- createFile path pidFileMode
  setLock fd (WriteLock, AbsoluteSeek, 0, 0)
  my_pid <- getProcessID
  _ <- fdWrite fd (show my_pid ++ "\n")
  return fd

-- | Wrapper over '_writePidFile' that transforms IO exceptions into a
-- 'Bad' value.
writePidFile :: FilePath -> IO (Result Fd)
writePidFile path = do
  catch (fmap Ok $ _writePidFile path) (return . Bad . show)

-- | Sets up a daemon's environment.
setupDaemonEnv :: FilePath -> FileMode -> IO ()
setupDaemonEnv cwd umask = do
  changeWorkingDirectory cwd
  _ <- setFileCreationMask umask
  _ <- createSession
  return ()

-- | Run an I/O action as a daemon.
--
-- WARNING: this only works in single-threaded mode (either using the
-- single-threaded runtime, or using the multi-threaded one but with
-- only one OS thread, i.e. -N1).
--
-- FIXME: this doesn't support error reporting and the prepfn
-- functionality.
daemonize :: IO () -> IO ()
daemonize action = do
  -- first fork
  _ <- forkProcess $ do
    -- in the child
    setupDaemonEnv "/" (unionFileModes groupModes otherModes)
    _ <- forkProcess action
    exitImmediately ExitSuccess
  exitImmediately ExitSuccess

-- | Generic daemon startup.
genericMain :: GanetiDaemon -> [OptType] -> (DaemonOptions -> IO ()) -> IO ()
genericMain daemon options main = do
  let progname = daemonName daemon
  (opts, args) <- parseArgs progname options

  when (optShowHelp opts) $ do
    putStr $ usageHelp progname options
    exitWith ExitSuccess
  when (optShowVer opts) $ do
    printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
           progname Version.version
           compilerName (Data.Version.showVersion compilerVersion)
           os arch :: IO ()
    exitWith ExitSuccess
  unless (null args) $ do
         hPutStrLn stderr "This program doesn't take any arguments"
         exitWith $ ExitFailure C.exitFailure

  unless (optNoUserChecks opts) $ do
    runtimeEnts <- getEnts
    case runtimeEnts of
      Bad msg -> do
        hPutStrLn stderr $ "Can't find required user/groups: " ++ msg
        exitWith $ ExitFailure C.exitFailure
      Ok ents -> verifyDaemonUser daemon ents

  let processFn = if optDaemonize opts then daemonize else id
  processFn $ innerMain daemon opts (main opts)

-- | Inner daemon function.
--
-- This is executed after daemonization.
innerMain :: GanetiDaemon -> DaemonOptions -> IO () -> IO ()
innerMain daemon opts main = do
  setupLogging (daemonLogFile daemon) (daemonName daemon) (optDebug opts)
                 (not (optDaemonize opts)) False
  pid_fd <- writePidFile (daemonPidFile daemon)
  case pid_fd of
    Bad msg -> do
         hPutStrLn stderr $ "Cannot write PID file; already locked? Error: " ++
                   msg
         exitWith $ ExitFailure 1
    _ -> return ()
  logNotice "starting"
  main