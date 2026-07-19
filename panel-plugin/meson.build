project(
  'xfce-zai-plugin',
  'c',
  version: '0.1.0',
  default_options: ['warning_level=2', 'c_std=c11'],
)

cc = meson.get_compiler('c')

dep_libxfce4panel = dependency('libxfce4panel-2.0', version: '>= 4.14')
dep_gtk           = dependency('gtk+-3.0',        version: '>= 3.22')
dep_json          = dependency('json-glib-1.0')

plugindir  = dep_libxfce4panel.get_variable('plugindir',  pkgconfig: 'libxfce4panel-2.0')
desktopdir = dep_libxfce4panel.get_variable('desktopdir', pkgconfig: 'libxfce4panel-2.0')

# Hardcode the script path so the plugin knows what to spawn at runtime.
# Override with -Dscript=... if you cloned elsewhere.
script = get_option('script')

shared_module(
  'zai-plugin',
  'src/zai-panel-plugin.c',
  dependencies: [dep_libxfce4panel, dep_gtk, dep_json, dependency('glib-2.0')],
  c_args: ['-DZAI_SCRIPT="' + script + '"'],
  install: true,
  install_dir: plugindir,
  install_rpath: '',
)

# Panel discovery file (lets "Add new items…" find it)
configure_file(
  input:  'zai-limits.desktop.in',
  output: 'zai-limits.desktop',
  configuration: configuration_data(),
  install: true,
  install_dir: desktopdir,
)
