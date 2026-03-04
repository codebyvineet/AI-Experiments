import React, { useState, useEffect } from 'react';
import { listItems, createItem, updateItem, deleteItem } from '../api';

export default function ItemsPanel({ token, user }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ name: '', description: '', category: '', price: '' });
  const [error, setError] = useState('');

  const isReadOnly = user?.role === 'read_only';

  const load = async () => {
    setLoading(true);
    try {
      const data = await listItems(token);
      setItems(data.items || data || []);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const payload = { ...form, price: parseFloat(form.price) || 0 };
      if (editingId) {
        await updateItem(token, editingId, payload);
      } else {
        await createItem(token, payload);
      }
      setShowForm(false);
      setEditingId(null);
      setForm({ name: '', description: '', category: '', price: '' });
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleEdit = (item) => {
    setEditingId(item.id || item._id);
    setForm({
      name: item.name || '',
      description: item.description || '',
      category: item.category || '',
      price: item.price?.toString() || ''
    });
    setShowForm(true);
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this item?')) return;
    try {
      await deleteItem(token, id);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">📦 Items</h2>
        {!isReadOnly && (
          <button
            onClick={() => { setShowForm(!showForm); setEditingId(null); setForm({ name: '', description: '', category: '', price: '' }); }}
            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm"
          >
            {showForm ? 'Cancel' : '+ Create Item'}
          </button>
        )}
      </div>

      {/* Permissions banner */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
        <div className="flex items-center gap-4 text-sm">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
            user?.role === 'admin' ? 'bg-purple-600/30 text-purple-300' :
            user?.role === 'user' ? 'bg-blue-600/30 text-blue-300' :
            'bg-gray-600/30 text-gray-300'
          }`}>{user?.role}</span>
          <span>{isReadOnly ? '✅' : '✅'} Read</span>
          <span>{!isReadOnly ? '✅' : '❌'} Write</span>
          <span>{!isReadOnly ? '✅' : '❌'} Delete</span>
          {isReadOnly && <span className="text-yellow-400 ml-auto">⚠️ Write operations will be denied</span>}
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 text-red-300 rounded p-3 text-sm">{error}</div>
      )}

      {/* Form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
          <h3 className="font-medium">{editingId ? 'Edit Item' : 'Create Item'}</h3>
          <div className="grid grid-cols-2 gap-3">
            <input
              placeholder="Name"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white"
              required
            />
            <input
              placeholder="Category"
              value={form.category}
              onChange={e => setForm({ ...form, category: e.target.value })}
              className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white"
            />
            <input
              placeholder="Description"
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white col-span-2"
            />
            <input
              placeholder="Price"
              type="number"
              step="0.01"
              value={form.price}
              onChange={e => setForm({ ...form, price: e.target.value })}
              className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white"
            />
          </div>
          <button type="submit" className="px-4 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded text-sm">
            {editingId ? 'Update' : 'Create'}
          </button>
        </form>
      )}

      {/* Items list */}
      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : items.length === 0 ? (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-8 text-center text-gray-400">
          No items yet. Create one to get started.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map(item => (
            <div key={item.id || item._id} className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-center justify-between">
              <div>
                <div className="font-medium">{item.name}</div>
                <div className="text-sm text-gray-400">
                  {item.description && <span>{item.description} · </span>}
                  {item.category && <span className="text-purple-400">{item.category}</span>}
                  {item.price != null && <span className="ml-2 text-green-400">${item.price}</span>}
                </div>
              </div>
              {!isReadOnly && (
                <div className="flex gap-2">
                  <button onClick={() => handleEdit(item)} className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm">Edit</button>
                  <button onClick={() => handleDelete(item.id || item._id)} className="px-3 py-1 bg-red-700 hover:bg-red-600 rounded text-sm">Delete</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
