const express = require('express');
const router = express.Router();
const passport = require('passport');
const GoogleStrategy = require('passport-google-oauth20').Strategy;
const User = require('../models/User');
const { generateToken, protect } = require('../middleware/auth');

const otpStore = new Map(); // in-memory, cleared on server restart

router.post('/send-otp', async (req, res) => {
  const { email } = req.body;
  if (!email) return res.status(400).json({ message: 'Email required.' });
  const otp = Math.floor(100000 + Math.random()*900000);
  console.log("Generated OTP:", otp);
  otpStore.set(email.toLowerCase(), { otp, expires: Date.now() + 5 * 60 * 1000 });
  console.log(`\n🔐 OTP for ${email}: ${otp}  (valid 5 minutes)\n`);
  res.json({ message: 'OTP sent (check server terminal for demo).' });
});

router.post('/verify-otp', async (req, res) => {
  const { email, otp } = req.body;
  const record = otpStore.get(email?.toLowerCase());
  if (!record) return res.status(400).json({ message: 'No OTP found. Request a new one.' });
  if (Date.now() > record.expires) {
    otpStore.delete(email.toLowerCase());
    return res.status(400).json({ message: 'OTP expired. Please try again.' });
  }
  if (record.otp !== otp) return res.status(400).json({ message: 'Incorrect OTP.' });
  otpStore.delete(email.toLowerCase());
  res.json({ verified: true });
});

// ── Passport Google Strategy ──
passport.use(new GoogleStrategy({
  clientID:     process.env.GOOGLE_CLIENT_ID || 'YOUR_GOOGLE_CLIENT_ID',
  clientSecret: process.env.GOOGLE_CLIENT_SECRET || 'YOUR_GOOGLE_CLIENT_SECRET',
  callbackURL:  process.env.GOOGLE_CALLBACK_URL || 'http://localhost:5000/api/auth/google/callback'
},
async (accessToken, refreshToken, profile, done) => {
  try {
    const email = profile.emails[0].value;
    let user = await User.findOne({ email });

    if (user) {
      // Link Google ID if signing in with Google on an existing email account
      if (!user.googleId) {
        user.googleId = profile.id;
        user.authProvider = 'both';
        await user.save();
      }
    } else {
      // New user via Google
      user = await User.create({
        email,
        firstName: profile.name.givenName,
        lastName:  profile.name.familyName,
        googleId:  profile.id,
        authProvider: 'google',
        profileComplete: false
      });
    }
    return done(null, user);
  } catch (err) {
    return done(err, null);
  }
}));

passport.serializeUser((user, done) => done(null, user._id));
passport.deserializeUser(async (id, done) => {
  try {
    const user = await User.findById(id);
    done(null, user);
  } catch (err) { done(err, null); }
});

// ── POST /api/auth/register ──
router.post('/register', async (req, res) => {
  try {
    const { firstName, lastName, email, password } = req.body;

    if (!email || !password || !firstName) {
      return res.status(400).json({ message: 'First name, email, and password are required.' });
    }
    if (password.length < 8) {
      return res.status(400).json({ message: 'Password must be at least 8 characters.' });
    }

    const existing = await User.findOne({ email: email.toLowerCase() });
    if (existing) {
      return res.status(409).json({ message: 'An account with this email already exists.' });
    }

    const user = await User.create({ firstName, lastName, email, password, authProvider: 'email' });
    const token = generateToken(user._id);

    res.status(201).json({
      token,
      user: {
        id: user._id,
        firstName: user.firstName,
        lastName: user.lastName,
        email: user.email,
        profileComplete: user.profileComplete,
        authProvider: user.authProvider
      }
    });
  } catch (err) {
    console.error('Register error:', err);
    res.status(500).json({ message: 'Server error during registration.' });
  }
});

// ── POST /api/auth/login ──
router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    if (!email || !password) {
      return res.status(400).json({ message: 'Email and password are required.' });
    }

    const user = await User.findOne({ email: email.toLowerCase() }).select('+password');
    if (!user) {
      return res.status(401).json({ message: 'Invalid email or password.' });
    }
    if (user.authProvider === 'google') {
      return res.status(401).json({ message: 'This account uses Google sign-in. Please use "Continue with Google".' });
    }

    const isMatch = await user.comparePassword(password);
    if (!isMatch) {
      return res.status(401).json({ message: 'Invalid email or password.' });
    }

    user.lastLogin = new Date();
    await user.save({ validateBeforeSave: false });

    const token = generateToken(user._id);
    res.json({
      token,
      user: {
        id: user._id,
        firstName: user.firstName,
        lastName: user.lastName,
        email: user.email,
        profileComplete: user.profileComplete,
        authProvider: user.authProvider
      }
    });
  } catch (err) {
    console.error('Login error:', err);
    res.status(500).json({ message: 'Server error during login.' });
  }
});

// ── GET /api/auth/google ──
router.get('/google',
  passport.authenticate('google', { scope: ['profile', 'email'] })
);

// ── GET /api/auth/google/callback ──
router.get('/google/callback',
  passport.authenticate('google', { failureRedirect: '/pages/auth/login.html?error=google_failed' }),
  (req, res) => {
    const token = generateToken(req.user._id);
    const user = req.user;
    // Redirect with token in query param — frontend picks it up
    const profileComplete = user.profileComplete ? 'true' : 'false';
    res.redirect(`/pages/auth/oauth-callback.html?token=${token}&profileComplete=${profileComplete}&firstName=${encodeURIComponent(user.firstName || '')}&email=${encodeURIComponent(user.email)}&id=${user._id}`);
  }
);

// ── DELETE /api/auth/delete ──
router.delete('/delete', protect, async (req, res) => {
  try {
    await User.findByIdAndDelete(req.user._id);
    res.json({ message: 'Account deleted successfully.' });
  } catch (err) {
    res.status(500).json({ message: 'Error deleting account.' });
  }
});

// ── GET /api/auth/me ──
router.get('/me', protect, (req, res) => {
  res.json({ user: req.user.toSafeObject() });
});

module.exports = router;
