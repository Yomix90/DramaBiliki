import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_theme.dart';
import '../../core/constants.dart';
import '../../core/localization.dart';
import '../../providers/app_providers.dart';

/// Profile tab: viewer card, stats and settings.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  void _showServerUrlDialog(BuildContext context, WidgetRef ref, AppLocale loc) {
    final prefs = ref.read(preferencesProvider);
    final textController = TextEditingController(text: prefs.getBaseUrl());

    showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: Text(loc.t('server_url'), style: const TextStyle(fontSize: 18)),
          content: TextField(
            controller: textController,
            keyboardType: TextInputType.url,
            autocorrect: false,
            style: const TextStyle(color: Colors.white),
            decoration: const InputDecoration(hintText: AppConstants.defaultBaseUrl),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: Text(loc.t('cancel'), style: const TextStyle(color: AppTheme.textSecondary)),
            ),
            ElevatedButton(
              onPressed: () async {
                var url = textController.text.trim();
                while (url.endsWith('/')) {
                  url = url.substring(0, url.length - 1);
                }
                if (Uri.tryParse(url)?.hasScheme != true) return;
                await prefs.setBaseUrl(url);
                // A token from another server is meaningless here: re-register on next call.
                await prefs.clearAuthToken();
                ref.read(apiClientProvider).updateBaseUrl(url);
                ref.invalidate(authInitProvider);
                refreshWatchState(ref);
                ref.invalidate(genresProvider);
                ref.invalidate(pagedSeriesProvider);
                if (dialogContext.mounted) Navigator.pop(dialogContext);
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(loc.t('server_url_updated'))));
                }
              },
              child: Text(loc.t('save')),
            ),
          ],
        );
      },
    ).whenComplete(textController.dispose);
  }

  void _showLanguagePicker(BuildContext context, WidgetRef ref, AppLocale loc, String current) {
    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final code in const ['en', 'fr', 'ar'])
              ListTile(
                title: Text(
                  loc.t('language_$code'),
                  style: TextStyle(fontWeight: code == current ? FontWeight.w800 : FontWeight.w500),
                ),
                trailing: code == current ? const Icon(Icons.check_circle_rounded, color: AppTheme.primary) : null,
                onTap: () {
                  ref.read(localeProvider.notifier).setLocale(code);
                  Navigator.pop(sheetContext);
                },
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final currentLang = ref.watch(localeProvider);
    final loc = AppLocale(currentLang);
    final settings = ref.watch(settingsProvider);
    final prefs = ref.watch(preferencesProvider);
    final library = ref.watch(libraryProvider).value;
    final deviceId = prefs.getDeviceId();

    return Scaffold(
      backgroundColor: AppTheme.background,
      body: ListView(
        padding: EdgeInsets.fromLTRB(16, MediaQuery.paddingOf(context).top + 16, 16, 24),
        children: [
          // Viewer card
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [AppTheme.primary.withValues(alpha: 0.28), AppTheme.card],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: AppTheme.border),
            ),
            child: Column(
              children: [
                Row(
                  children: [
                    Container(
                      width: 56,
                      height: 56,
                      decoration: const BoxDecoration(gradient: AppTheme.primaryGradient, shape: BoxShape.circle),
                      child: const Icon(Icons.person_rounded, color: Colors.white, size: 32),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(loc.t('guest'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                          const SizedBox(height: 2),
                          Text(
                            'ID ${deviceId.substring(0, deviceId.length < 8 ? deviceId.length : 8).toUpperCase()}',
                            style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    _Stat(value: library?.favorites.length, label: loc.t('stats_list')),
                    Container(width: 1, height: 28, color: AppTheme.border),
                    _Stat(value: library?.history.length, label: loc.t('stats_watched')),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),

          _SectionHeader(loc.t('settings')),
          _Group(children: [
            ListTile(
              leading: const Icon(Icons.language_rounded, color: AppTheme.textSecondary),
              title: Text(loc.t('language'), style: const TextStyle(fontSize: 14)),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(loc.t('language_$currentLang'), style: const TextStyle(color: AppTheme.textMuted, fontSize: 13)),
                  const Icon(Icons.chevron_right_rounded, color: AppTheme.textMuted),
                ],
              ),
              onTap: () => _showLanguagePicker(context, ref, loc, currentLang),
            ),
            SwitchListTile(
              secondary: const Icon(Icons.skip_next_rounded, color: AppTheme.textSecondary),
              title: Text(loc.t('autoplay_next'), style: const TextStyle(fontSize: 14)),
              subtitle: Text(loc.t('autoplay_next_desc'), style: const TextStyle(color: AppTheme.textMuted, fontSize: 12)),
              value: settings.autoplayNext,
              onChanged: (v) => ref.read(settingsProvider.notifier).setAutoplayNext(v),
            ),
            SwitchListTile(
              secondary: const Icon(Icons.closed_caption_rounded, color: AppTheme.textSecondary),
              title: Text(loc.t('subtitles_default'), style: const TextStyle(fontSize: 14)),
              value: settings.subtitles,
              onChanged: (v) => ref.read(settingsProvider.notifier).setSubtitles(v),
            ),
            SwitchListTile(
              secondary: const Icon(Icons.data_saver_on_rounded, color: AppTheme.textSecondary),
              title: Text(loc.t('data_saver'), style: const TextStyle(fontSize: 14)),
              subtitle: Text(loc.t('data_saver_desc'), style: const TextStyle(color: AppTheme.textMuted, fontSize: 12)),
              value: settings.dataSaver,
              onChanged: (v) => ref.read(settingsProvider.notifier).setDataSaver(v),
            ),
            ListTile(
              leading: const Icon(Icons.dns_rounded, color: AppTheme.textSecondary),
              title: Text(loc.t('server_url'), style: const TextStyle(fontSize: 14)),
              subtitle: Text(prefs.getBaseUrl(), style: const TextStyle(color: AppTheme.textMuted, fontSize: 12)),
              trailing: const Icon(Icons.edit_rounded, color: AppTheme.primary, size: 18),
              onTap: () => _showServerUrlDialog(context, ref, loc),
            ),
          ]),
          const SizedBox(height: 24),

          _SectionHeader(loc.t('about')),
          _Group(children: [
            ListTile(
              leading: const Icon(Icons.info_outline_rounded, color: AppTheme.textSecondary),
              title: const Text(AppConstants.appName, style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
              subtitle: Text(
                "${loc.t('version')} ${AppConstants.appVersion}",
                style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
              ),
            ),
          ]),
        ],
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final int? value;
  final String label;

  const _Stat({required this.value, required this.label});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        children: [
          Text(value?.toString() ?? '–', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
          const SizedBox(height: 2),
          Text(label, style: const TextStyle(color: AppTheme.textSecondary, fontSize: 12)),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;

  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(start: 4, bottom: 8),
      child: Text(
        title.toUpperCase(),
        style: const TextStyle(color: AppTheme.textMuted, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.8),
      ),
    );
  }
}

class _Group extends StatelessWidget {
  final List<Widget> children;

  const _Group({required this.children});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border, width: 0.8),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const Divider(height: 1, indent: 56, color: AppTheme.border),
            children[i],
          ],
        ],
      ),
    );
  }
}
