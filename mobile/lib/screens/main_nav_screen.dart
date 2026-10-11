import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/app_theme.dart';
import '../core/localization.dart';
import '../providers/app_providers.dart';
import 'foryou/for_you_screen.dart';
import 'home/home_screen.dart';
import 'library/library_screen.dart';
import 'settings/settings_screen.dart';

class MainNavScreen extends ConsumerStatefulWidget {
  const MainNavScreen({super.key});

  @override
  ConsumerState<MainNavScreen> createState() => _MainNavScreenState();
}

class _MainNavScreenState extends ConsumerState<MainNavScreen> {
  static const _forYouTab = 1;
  static const _libraryTab = 2;

  int _currentIndex = 0;

  void _select(int idx) {
    if (idx == _currentIndex) return;
    // Library content changes while watching: refresh it when the tab is opened.
    if (idx == _libraryTab) ref.invalidate(libraryProvider);
    setState(() => _currentIndex = idx);
  }

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));
    final immersive = _currentIndex == _forYouTab;

    final items = [
      (Icons.home_outlined, Icons.home_rounded, loc.t('tab_home')),
      (Icons.play_circle_outline_rounded, Icons.play_circle_filled_rounded, loc.t('tab_for_you')),
      (Icons.bookmark_border_rounded, Icons.bookmark_rounded, loc.t('tab_my_list')),
      (Icons.person_outline_rounded, Icons.person_rounded, loc.t('tab_profile')),
    ];

    return PopScope(
      // Back from another tab returns Home instead of leaving the app.
      canPop: _currentIndex == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _select(0);
      },
      child: Scaffold(
        backgroundColor: immersive ? Colors.black : AppTheme.background,
        body: IndexedStack(
          index: _currentIndex,
          children: [
            const HomeScreen(),
            ForYouScreen(isActive: _currentIndex == _forYouTab),
            LibraryScreen(onExplore: () => _select(0)),
            const SettingsScreen(),
          ],
        ),
        bottomNavigationBar: Container(
          decoration: BoxDecoration(
            color: immersive ? Colors.black : AppTheme.surface,
            border: Border(top: BorderSide(color: immersive ? Colors.white10 : AppTheme.border, width: 0.5)),
          ),
          child: SafeArea(
            top: false,
            child: SizedBox(
              height: 58,
              child: Row(
                children: [
                  for (var i = 0; i < items.length; i++)
                    Expanded(
                      child: _NavItem(
                        icon: items[i].$1,
                        activeIcon: items[i].$2,
                        label: items[i].$3,
                        selected: i == _currentIndex,
                        onTap: () => _select(i),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  final IconData icon;
  final IconData activeIcon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _NavItem({
    required this.icon,
    required this.activeIcon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = selected ? Colors.white : AppTheme.textMuted;
    return InkResponse(
      onTap: onTap,
      radius: 36,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          selected
              ? ShaderMask(
                  shaderCallback: (rect) => AppTheme.primaryGradient.createShader(rect),
                  child: Icon(activeIcon, color: Colors.white, size: 26),
                )
              : Icon(icon, color: color, size: 26),
          const SizedBox(height: 2),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}
