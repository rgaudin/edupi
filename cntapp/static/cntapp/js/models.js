var Directory = Backbone.Model.extend({
    defaults: {
        id: 0,
        name: "Not specified"
    },

    initialize: function () {
        console.log("New Directory.")
    },

    url: function () {
        return '/api/directories/' + this.id + '/';
    }
});
