import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../models/account.dart';
import '../../providers/app_providers.dart';

/// Login / sign-up. A guest who signs up keeps its list and history.
class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _username = TextEditingController();
  bool _register = false;
  bool _busy = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _username.dispose();
    super.dispose();
  }

  Future<void> _submit(AppLocale loc) async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final repo = ref.read(repositoryProvider);
    try {
      if (_register) {
        await repo.register(_email.text.trim(), _password.text, _username.text.trim());
      } else {
        await repo.login(_email.text.trim(), _password.text);
      }
      if (!mounted) return;
      refreshSession(ref);
      Navigator.pop(context, true);
    } on AuthException catch (e) {
      setState(() => _error = e.message.isNotEmpty ? e.message : loc.t('auth_error'));
    } catch (_) {
      setState(() => _error = loc.t('auth_error'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Container(
                      width: 64,
                      height: 64,
                      decoration: BoxDecoration(gradient: AppTheme.primaryGradient, borderRadius: BorderRadius.circular(18)),
                      child: const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 42),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    loc.t(_register ? 'register' : 'login'),
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    loc.t('login_prompt'),
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                  ),
                  const SizedBox(height: 24),

                  // Mode switch
                  Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(color: AppTheme.surfaceLight, borderRadius: BorderRadius.circular(24)),
                    child: Row(
                      children: [
                        for (final reg in [false, true])
                          Expanded(
                            child: GestureDetector(
                              onTap: _busy ? null : () => setState(() {
                                _register = reg;
                                _error = null;
                              }),
                              child: AnimatedContainer(
                                duration: const Duration(milliseconds: 200),
                                padding: const EdgeInsets.symmetric(vertical: 10),
                                decoration: BoxDecoration(
                                  gradient: _register == reg ? AppTheme.primaryGradient : null,
                                  borderRadius: BorderRadius.circular(20),
                                ),
                                alignment: Alignment.center,
                                child: Text(loc.t(reg ? 'register' : 'login'), style: const TextStyle(fontWeight: FontWeight.w700)),
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  if (_register) ...[
                    TextFormField(
                      controller: _username,
                      textInputAction: TextInputAction.next,
                      decoration: InputDecoration(
                        hintText: loc.t('username'),
                        prefixIcon: const Icon(Icons.person_outline_rounded, color: AppTheme.textMuted),
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],
                  TextFormField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autocorrect: false,
                    textInputAction: TextInputAction.next,
                    decoration: InputDecoration(
                      hintText: loc.t('email'),
                      prefixIcon: const Icon(Icons.alternate_email_rounded, color: AppTheme.textMuted),
                    ),
                    validator: (v) => RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch((v ?? '').trim()) ? null : loc.t('email_invalid'),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _password,
                    obscureText: _obscure,
                    textInputAction: TextInputAction.done,
                    onFieldSubmitted: (_) => _submit(loc),
                    decoration: InputDecoration(
                      hintText: loc.t('password'),
                      prefixIcon: const Icon(Icons.lock_outline_rounded, color: AppTheme.textMuted),
                      suffixIcon: IconButton(
                        icon: Icon(_obscure ? Icons.visibility_off_rounded : Icons.visibility_rounded, color: AppTheme.textMuted),
                        onPressed: () => setState(() => _obscure = !_obscure),
                      ),
                    ),
                    validator: (v) => (v ?? '').length >= 6 ? null : loc.t('password_short'),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 14),
                    Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFFFF6B81))),
                  ],
                  const SizedBox(height: 22),
                  SizedBox(
                    height: 50,
                    child: DecoratedBox(
                      decoration: BoxDecoration(gradient: AppTheme.primaryGradient, borderRadius: BorderRadius.circular(25)),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: Colors.transparent, shadowColor: Colors.transparent),
                        onPressed: _busy ? null : () => _submit(loc),
                        child: _busy
                            ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                            : Text(loc.t(_register ? 'register' : 'login'), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                      ),
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
