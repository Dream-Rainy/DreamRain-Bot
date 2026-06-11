# Third Party Notices

This file records third-party code and assets that are included in this
repository. It is a best-effort engineering notice, not legal advice. The
project's root `LICENSE` applies to DreamRain-Bot code unless a file, directory,
submodule, or notice below states otherwise.

For Python package dependencies that are installed from package indexes instead
of vendored into this repository, see `pyproject.toml`, `requirements.txt`, and
`uv.lock`. Generate a dependency license report separately when preparing a
release.

## Included Third-Party Code

### nonebot_plugin_crazy_thursday

- Path: `src/plugins/nonebot_plugin_crazy_thursday/`
- Source: <https://github.com/MinatoAquaCrews/nonebot_plugin_crazy_thursday>
- Package metadata: <https://pypi.org/project/nonebot_plugin_crazy_thursday/>
- Author: KafCoppelia
- License: MIT
- Local changes: included as local plugin code; may have project integration
  changes.
- Notes: upstream package description says this plugin is modified from
  `HoshinoBot-fucking_crazy_thursday`.

### nonebot_plugin_fortune

- Path: `src/plugins/nonebot_plugin_fortune/`
- Source: <https://github.com/MinatoAquaCrews/nonebot_plugin_fortune>
- Package metadata: <https://pypi.org/project/nonebot-plugin-fortune/>
- Author: KafCoppelia
- License: MIT
- Local changes: included as local plugin code with project-specific changes.

### nonebot_plugin_tarot

- Path: `src/plugins/nonebot_plugin_tarot/`
- Source: <https://github.com/MinatoAquaCrews/nonebot_plugin_tarot>
- Package metadata: <https://pypi.org/project/nonebot_plugin_tarot/>
- Author: KafCoppelia
- License: MIT
- Local changes: included as local plugin code with project-specific changes.

### nonebot_plugin_githubcard

- Path: `src/plugins/nonebot_plugin_githubcard/`
- Source: <https://github.com/ElainaFanBoy/nonebot_plugin_githubcard>
- Package metadata: <https://pypi.org/project/nonebot-plugin-githubcard/>
- License reference: <https://data.safetycli.com/packages/pypi/nonebot-plugin-githubcard/>
- Author: Nanako
- License: MIT
- Local changes: included as local plugin code with project-specific changes.

### nonebot_plugin_picstatus

- Path: `src/plugins/nonebot_plugin_picstatus/`
- Source: <https://github.com/lgc-NB2Dev/nonebot-plugin-picstatus>
- Package metadata: <https://pypi.org/project/nonebot-plugin-picstatus/>
- Author: student_2333
- License: MIT
- Local changes: included as local plugin code with project-specific changes.

### nonebot_plugin_wordle

- Path: `src/plugins/nonebot_plugin_wordle/`
- Source: <https://github.com/noneplugin/nonebot-plugin-wordle>
- Package metadata: <https://pypi.org/project/nonebot-plugin-wordle/>
- License reference: <https://data.safetycli.com/packages/pypi/nonebot-plugin-wordle/>
- Copyright holder: noneplugin/nonebot-plugin-wordle contributors
- License: MIT
- Local changes: included as local plugin code.

### kanna_note

- Path: `src/plugins/kanna_note/`
- Source: <https://github.com/SonderXiaoming/kanna_note>
- Copyright holder: SonderXiaoming/kanna_note contributors
- License: Apache-2.0
- License text: `src/plugins/kanna_note/LICENSE.txt`
- Local changes: migrated and adapted for NoneBot, SQLAlchemy-based external
  sqlite access, and project storage/runtime conventions.

### nonebot_plugin_pcrjjc

- Path: `src/plugins/nonebot_plugin_pcrjjc/`
- Source: <https://github.com/reine-ishyanami/nonebot-plugin-pcrjjc>
- Package metadata: <https://pypi.org/project/nonebot-plugin-pcrjjc/>
- License reference: <https://getsafety.com/packages/pypi/nonebot-plugin-pcrjjc/>
- License: AGPL-3.0
- Local changes: included as local plugin code with project-specific changes.
- Notes: upstream includes the official GNU AGPLv3 license text but does not
  explicitly state whether the license is `AGPL-3.0-only` or
  `AGPL-3.0-or-later`, so this directory is not annotated in `REUSE.toml` yet.

### nonebot_plugin_repeater

- Path: `src/plugins/nonebot_plugin_repeater/`
- Source: <https://github.com/Utmost-Happiness-Planet/nonebot-plugin-repeater>
- License: GPL-3.0
- Local changes: included as local plugin code with project-specific changes.
- Notes: upstream includes the official GNU GPLv3 license text but does not
  explicitly state whether the license is `GPL-3.0-only` or
  `GPL-3.0-or-later`, so this directory is not annotated in `REUSE.toml` yet.

### pokepoke_miss

- Path: `src/plugins/pokepoke_miss/`
- Source in local metadata: <https://github.com/shengwang52005/pokepoke_miss>
- Source in README: <https://github.com/MWNya520/pokepoke_miss>
- License: MIT
- Local changes: included as local plugin code with project-specific changes.

### priconne

- Path: `src/plugins/priconne/`
- Source in README: <https://github.com/SonderXiaoming/kanna_connection_redive_2>
- License: no repository-level license identified
- Local changes: migrated and adapted for this project.
- Notes: at least the following files carry their own GPL-3.0 notice from
  GWYOG-Hoshino-plugins and are annotated in `REUSE.toml`:
  - `src/plugins/priconne/games/avatar_guess.py`
  - `src/plugins/priconne/games/desc_guess.py`

### autopcr

- Path: `src/submodule/autopcr/`
- Source: <https://github.com/cc004/autopcr>
- Local form: git submodule at commit `93d3d5bee762952f86a33298b824057871d7f418`
- License: CC-BY-NC-SA-4.0
- License text: `src/submodule/autopcr/LICENSE`
- Notes: this license includes NonCommercial and ShareAlike terms. It is not
  covered by the root MIT license.

## Package Dependencies

The following external plugins are installed as dependencies rather than
vendored source, according to the project README and dependency manifests:

- `nonebot-plugin-whateat-pic` from
  <https://github.com/MinatoAquaCrews/nonebot_plugin_what2eat>
- `nonebot-plugin-analysis-bilibili` from
  <https://github.com/mengshouer/nonebot_plugin_analysis_bilibili>
- `nonebot-plugin-memes` from
  <https://github.com/MemeCrafters/nonebot-plugin-memes>
- `nonebot-plugin-wordcloud` from
  <https://github.com/he0119/nonebot-plugin-wordcloud>
- `nonebot-plugin-guess-song` from
  <https://github.com/apshuang/nonebot-plugin-guess-song>

When distributing release artifacts, generate a full dependency license report
from the resolved environment and ship it with the release notes or artifact.
