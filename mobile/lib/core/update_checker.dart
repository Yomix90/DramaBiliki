import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';
import '../providers/app_providers.dart';
import 'app_theme.dart';
import 'constants.dart';
import 'localization.dart';

/// Asks the bridge whether a newer APK is published and shows the update dialog.
/// A forced update cannot be dismissed.
Future<void> checkForAppUpdate(BuildContext context, WidgetRef ref) async {
  try {
    final info = await ref.read(repositoryProvider).checkVersion(AppConstants.appVersion);
    if (!info.hasUpdate || info.downloadUrl.isEmpty || !context.mounted) return;
    final loc = AppLocale(ref.read(localeProvider));

    await showDialog<void>(
      context: context,
      barrierDismissible: !info.forceUpdate,
      builder: (dialogContext) => PopScope(
        canPop: !info.forceUpdate,
        child: AlertDialog(
          title: Row(
            children: [
              const Icon(Icons.system_update_rounded, color: AppTheme.primary),
              const SizedBox(width: 10),
              Expanded(child: Text(loc.t(info.forceUpdate ? 'update_required' : 'update_available'))),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${loc.t('update_desc')} (${AppConstants.appVersion} → ${info.latestVersion})',
                  style: const TextStyle(color: AppTheme.textSecondary)),
              if (info.releaseNotes.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(info.releaseNotes, style: const TextStyle(height: 1.4)),
              ],
            ],
          ),
          actions: [
            if (!info.forceUpdate)
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: Text(loc.t('later'), style: const TextStyle(color: AppTheme.textSecondary)),
              ),
            ElevatedButton.icon(
              icon: const Icon(Icons.download_rounded),
              label: Text(loc.t('update_now')),
              onPressed: () async {
                await launchUrl(Uri.parse(info.downloadUrl), mode: LaunchMode.externalApplication);
                if (!info.forceUpdate && dialogContext.mounted) Navigator.pop(dialogContext);
              },
            ),
          ],
        ),
      ),
    );
  } catch (_) {
    // Offline or old server: never block the app on the update check.
  }
}
