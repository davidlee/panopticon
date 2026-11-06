{
  description = "panopticon — local desktop-behaviour capture";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    devshell.url = "github:numtide/devshell";
    agents = {
      url = "github:davidlee/nix-config?dir=flakes/agents";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    doctrine.url = "github:davidlee/doctrine";
    # quotient's form-family builder, for quotientForms below.
    quotient = {
      url = "github:davidlee/quotient/v0.6.1";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    devshell,
    agents,
    doctrine,
    quotient,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {
        inherit system;
        overlays = [devshell.overlays.default];
      };
      inherit (pkgs.stdenv.hostPlatform) isLinux;

      panopticon = pkgs.python3Packages.buildPythonApplication {
        pname = "panopticon";
        inherit ((builtins.fromTOML (builtins.readFile ./pyproject.toml)).project) version;
        pyproject = true;
        src = ./.;
        build-system = with pkgs.python3Packages; [hatchling];
        dependencies = with pkgs.python3Packages; [evdev i3ipc lxml markdownify];
        # git: the git-poller suite (tests/test_git_poller.py) shells out to a
        # real git binary — the sandbox has none unless we add it here.
        nativeCheckInputs =
          (with pkgs.python3Packages; [pytestCheckHook pytest-asyncio])
          ++ [pkgs.git];
        meta.mainProgram = "panopticon-desktop";
      };

      doctrine-pkg = doctrine.packages.${system}.default;

      # Project tools injected into each jail so agents can run the same
      # build/test/lint loop a human would.
      projectPkgs = with pkgs; [
        (python3.withPackages (ps:
          with ps; [
            evdev
            i3ipc
            pytest
            pytest-asyncio
            lxml
            markdownify
          ]))
        web-ext
        ruff
        uv
        just
        bun
      ];

      jailLib = agents.lib.${system}.mkJailedAgents {};

      # Expose the host niri IPC socket to the jails so the compositor/niri
      # capture path (frames() -> $NIRI_SOCKET) can reach the live compositor,
      # mirroring the PULSE_SERVER audio passthrough in baseJailOptions. The
      # socket name carries a per-session suffix (niri.wayland-<id>.sock), so
      # both the env var and the bind resolve at launch time from the host's
      # $NIRI_SOCKET — the apiKeyPassThrough runtime-forward pattern, not a
      # baked constant. Unset on the host -> no setenv + a bind-try of an
      # absent path (skipped), and the watcher backs off
      # (compositor_disconnected) as designed. Never fall back to /dev/null:
      # bwrap mounts every --bind nodev, so it would shadow the --dev
      # /dev/null and every open of it (each pi spawn) fails EACCES.
      niriOptions = with jailLib.combinators; [
        (try-fwd-env "NIRI_SOCKET")
        (try-readwrite (noescape "\"\${NIRI_SOCKET:-/nonexistent/niri.sock}\""))
      ];

      jailOptions = niriOptions;

      # Every jail reaches models through the local LLM gateway with the
      # shared `pi` key (~/.config/llm-gateway/keys/pi); no provider key
      # enters a jail.
      gateway = jailLib.gatewayClient "pi";

      jailPkgs = {
        jailed-pi = jailLib.makeJailedPi {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = jailOptions;
          allowSelfAsSubagent = true;
          maxSubagentDepth = 2;
          inherit gateway;
        };
        jailed-claude = jailLib.makeJailedClaude {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = jailOptions;
          inherit gateway;
        };
        jailed-codex = jailLib.makeJailedCodex {
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = jailOptions;
          inherit gateway;
        };
        claude = jailLib.agentsByName.claude;
        codex = jailLib.agentsByName.codex;
        jailed-shell = jailLib.makeJailedAgent {
          name = "shell";
          agent = pkgs.zsh;
          profile = "specDev";
          extraPkgs = projectPkgs;
          extraOptions = jailOptions;
          subagents = ["pi" "claude"];
          inherit gateway;
        };
      };

      # quotient's per-call forms for this root (`quotient help form`): the
      # jails quotient's `pi_agent` runs a delegate in, on the gateway's pi
      # key, with the project's toolchain. `just quotient-forms`, then
      # `quotient allow`.
      quotientForms = pkgs.lib.optionalAttrs isLinux (let
        family = jailLib.quotientFormFamily {
          inherit quotient;
          packages = projectPkgs ++ (with pkgs; [bash findutils gnugrep gnused gawk ripgrep fd git]);
        };
      in {
        quotient-read = family.read;
        quotient-write = family.write;
      });
    in {
      packages =
        {
          default = panopticon;
          panopticon = panopticon;

          # The same `projectPkgs` the jails and the devshell get, as one
          # package, for a consumer that jails differently: oubliette runs the
          # agent inside a microVM, where a bwrap wrapper binding *host* paths
          # is meaningless, so it takes the tool set and builds its own
          # confinement around it. One list, so the VM and this devshell cannot
          # drift. `jailPkgs` is deliberately not in here — those are the
          # wrappers, not the tools.
          dev-tools = pkgs.buildEnv {
            name = "panopticon-dev-tools";
            paths = projectPkgs;
            ignoreCollisions = true;
          };
          # What the VM takes: `dev-tools` plus doctrine. The devshell and
          # jails use the host's install (agents' hostDoctrine), which a VM
          # does not have.
          capsule-tools = pkgs.buildEnv {
            name = "panopticon-capsule-tools";
            paths = projectPkgs ++ [doctrine-pkg];
            ignoreCollisions = true;
          };
        }
        // pkgs.lib.optionalAttrs isLinux jailPkgs
        // quotientForms;

      devShells.default = pkgs.devshell.mkShell {
        packages =
          projectPkgs
          ++ pkgs.lib.optionals isLinux (pkgs.lib.attrValues jailPkgs);

        commands = pkgs.lib.optionals isLinux [
          {
            name = "jpi";
            help = "jailed-pi $@";
            command = "jailed-pi \"$@\"";
          }
          {
            name = "jcl";
            help = "jailed-claude (--dangerously-skip-permissions for interactive)";
            command = ''
              case "''${1:-}" in
                marketplace|update|config|mcp) jailed-claude "$@" ;;
                *) jailed-claude --dangerously-skip-permissions "$@" ;;
              esac
            '';
          }
        ];
      };
    });
}
