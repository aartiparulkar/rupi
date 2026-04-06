const express = require('express');
const router = express.Router();
const User = require('../models/User');
const { protect } = require('../middleware/auth');

// ── GET /api/chat/history ── All sessions for this user
router.get('/history', protect, async (req, res) => {
  try {
    const user = await User.findById(req.user._id).select('chatSessions');
    const sessions = user.chatSessions.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    res.json({ sessions });
  } catch (err) {
    res.status(500).json({ message: 'Error fetching chat history.' });
  }
});

// ── POST /api/chat/session ── Start or save a session
router.post('/session', protect, async (req, res) => {
  try {
    const { agent, messages, preview } = req.body;
    if (!agent) return res.status(400).json({ message: 'Agent type is required.' });

    const newSession = { agent, messages: messages || [], preview: preview || '', updatedAt: new Date() };

    const user = await User.findByIdAndUpdate(
      req.user._id,
      { $push: { chatSessions: { $each: [newSession], $position: 0 } } },
      { new: true, select: 'chatSessions' }
    );

    const saved = user.chatSessions[0];
    res.status(201).json({ session: saved });
  } catch (err) {
    res.status(500).json({ message: 'Error saving chat session.' });
  }
});

// ── PUT /api/chat/session/:id ── Append messages to existing session
router.put('/session/:id', protect, async (req, res) => {
  try {
    const { messages, preview } = req.body;
    const user = await User.findOneAndUpdate(
      { _id: req.user._id, 'chatSessions._id': req.params.id },
      {
        $set: {
          'chatSessions.$.messages': messages,
          'chatSessions.$.preview': preview,
          'chatSessions.$.updatedAt': new Date()
        }
      },
      { new: true, select: 'chatSessions' }
    );

    const session = user.chatSessions.id(req.params.id);
    res.json({ session });
  } catch (err) {
    res.status(500).json({ message: 'Error updating chat session.' });
  }
});

// ── DELETE /api/chat/session/:id ──
router.delete('/session/:id', protect, async (req, res) => {
  try {
    await User.findByIdAndUpdate(
      req.user._id,
      { $pull: { chatSessions: { _id: req.params.id } } }
    );
    res.json({ message: 'Session deleted.' });
  } catch (err) {
    res.status(500).json({ message: 'Error deleting session.' });
  }
});

module.exports = router;
